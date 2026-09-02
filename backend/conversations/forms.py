"""Formulario de handoff (D-029, cerrada 2026-09-02) — RF-003, RF-022, RF-024.

Pedir datos al usuario NO pasa por el input del chat: el bot ofrece una TARJETA de formulario
(metadata `interaction` del mensaje, mismo mecanismo que los quick replies de D-028) y el
widget la dibuja con campos y un boton. Lo que el usuario envia llega a
`POST /chat/conversations/{id}/handoff`, se valida AQUI (nunca se confia en el cliente,
security-guidance) y queda en el hilo como un mensaje `FORM_RESPONSE` legible por el asesor.

Que se pide depende de quien es el usuario:
- Anonimo: nombre y correo obligatorios, telefono opcional (RF-003: sin correo no hay forma
  de buscarlo si cierra la pestaña), mas asunto y detalle.
- Autenticado: asunto y detalle; el correo solo si el JWT de VMC no lo trajo.

Modulo puro: sin DynamoDB ni FastAPI, para que el worker (que ofrece el formulario) y la API
(que lo valida) compartan la MISMA definicion sin importarse entre si.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Tipo de interaccion que el widget sabe dibujar como formulario.
HANDOFF_FORM = "HANDOFF_FORM"
HANDOFF_FORM_VERSION = 1

MAX_NAME_CHARS = 80
MAX_EMAIL_CHARS = 254
MAX_PHONE_CHARS = 20
MAX_SUBJECT_CHARS = 120
MIN_SUBJECT_CHARS = 3
MIN_DETAIL_CHARS = 10

# Validacion deliberadamente laxa: rechaza lo que claramente no es un correo/telefono sin
# pelearse con formatos legitimos. Verificar que el correo EXISTE es trabajo del asesor.
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")
_PHONE = re.compile(r"^\+?[0-9][0-9 ()\-]{5,}$")


class FormValidationError(ValueError):
    """Un campo no pasa. `field` le dice al widget que casilla marcar."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field


@dataclass(frozen=True, slots=True)
class HandoffForm:
    subject: str
    detail: str
    name: str | None = None
    email: str | None = None
    phone: str | None = None


# El formulario se pide en DOS pasos (decision de Aaron, 2026-09-02): primero quien eres,
# despues que te pasa. Cinco campos de golpe dentro de una burbuja de chat se leen como un
# tramite; dos pantallas cortas se leen como una conversacion.
#
# El PASO lo declara el servidor, campo por campo, y no lo adivina el widget por el nombre:
# quien decide que datos hacen falta es esta funcion (depende de si el usuario es anonimo o de
# si su JWT trajo correo), asi que tambien le toca decir donde va cada uno. Si el paso 1 se
# queda sin campos —el caso normal del autenticado— el widget dibuja un solo paso.
STEP_CONTACT = 1
STEP_CASE = 2


def handoff_form_spec(*, anonymous: bool, needs_email: bool) -> dict:
    """La metadata del mensaje del bot que el widget dibuja como tarjeta de formulario.

    Los `max` viajan para que el widget corte donde el servidor va a cortar; el servidor
    valida igual (el HTML se edita).
    """
    fields: list[dict] = []
    if anonymous:
        fields.append(_field("name", "Nombre", "text", STEP_CONTACT, required=True,
                             max=MAX_NAME_CHARS))
        fields.append(_field("email", "Correo", "email", STEP_CONTACT, required=True,
                             max=MAX_EMAIL_CHARS))
        fields.append(_field("phone", "Teléfono (opcional)", "tel", STEP_CONTACT,
                             required=False, max=MAX_PHONE_CHARS))
    elif needs_email:
        fields.append(_field("email", "Correo", "email", STEP_CONTACT, required=True,
                             max=MAX_EMAIL_CHARS))
    fields.append(_field("subject", "Asunto", "text", STEP_CASE, required=True,
                         max=MAX_SUBJECT_CHARS))
    fields.append(_field("detail", "Cuéntanos qué pasó", "textarea", STEP_CASE, required=True,
                         max=None))
    return {
        "interaction": {
            "type": HANDOFF_FORM,
            "version": HANDOFF_FORM_VERSION,
            "fields": fields,
            "submit": "Enviar al asesor",
        }
    }


def _field(
    name: str, label: str, kind: str, step: int, *, required: bool, max: int | None
) -> dict:
    spec = {"name": name, "label": label, "type": kind, "step": step, "required": required}
    if max is not None:
        spec["max"] = max
    return spec


def validate_handoff_form(
    form: HandoffForm, *, anonymous: bool, needs_email: bool, max_detail_chars: int
) -> HandoffForm:
    """Normaliza (strip) y valida contra las reglas de arriba; devuelve el formulario limpio
    o lanza FormValidationError con el campo culpable."""
    subject = _clean(form.subject)
    if len(subject) < MIN_SUBJECT_CHARS:
        raise FormValidationError("subject", "Cuéntanos el asunto en unas palabras")
    if len(subject) > MAX_SUBJECT_CHARS:
        raise FormValidationError("subject", f"El asunto supera los {MAX_SUBJECT_CHARS} caracteres")
    detail = _clean(form.detail)
    if len(detail) < MIN_DETAIL_CHARS:
        raise FormValidationError("detail", "Danos un poco más de detalle")
    if len(detail) > max_detail_chars:
        raise FormValidationError("detail", f"El detalle supera los {max_detail_chars} caracteres")

    name = _clean(form.name) if form.name else ""
    email = _clean(form.email).lower() if form.email else ""
    phone = _clean(form.phone) if form.phone else ""
    if anonymous:
        if not name:
            raise FormValidationError("name", "Necesitamos tu nombre")
        if len(name) > MAX_NAME_CHARS:
            raise FormValidationError("name", f"El nombre supera los {MAX_NAME_CHARS} caracteres")
    if anonymous or needs_email:
        if not email:
            raise FormValidationError("email", "Necesitamos un correo para contactarte")
    if email and (len(email) > MAX_EMAIL_CHARS or not _EMAIL.match(email)):
        raise FormValidationError("email", "Ese correo no parece válido")
    if phone and (len(phone) > MAX_PHONE_CHARS or not _PHONE.match(phone)):
        raise FormValidationError("phone", "Ese teléfono no parece válido")
    return HandoffForm(
        subject=subject,
        detail=detail,
        name=name or None,
        email=email or None,
        phone=phone or None,
    )


def summary_text(form: HandoffForm) -> str:
    """Contenido legible del mensaje FORM_RESPONSE: lo que ve el asesor en el hilo (y el
    usuario como eco de lo que envio). Los datos de contacto van solo si los dio."""
    lines = [f"Asunto: {form.subject}", "", form.detail]
    pairs = (("Nombre", form.name), ("Correo", form.email), ("Teléfono", form.phone))
    contact = [f"{label}: {value}" for label, value in pairs if value]
    if contact:
        lines += ["", *contact]
    return "\n".join(lines)


def _clean(value: str | None) -> str:
    # Colapsa espacios internos y quita controles: un campo de formulario es UNA linea, salvo
    # el detalle, donde los saltos de linea se respetan a proposito.
    if value is None:
        return ""
    return re.sub(r"[ \t]+", " ", value.replace("\r", "")).strip()
