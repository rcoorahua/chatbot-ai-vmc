"""Formulario de asesor (D-029, cerrada 2026-09-02; revisada por D-031) — RF-022, RF-024.

Pedir datos al usuario NO pasa por el input del chat: el bot ofrece una TARJETA de formulario
(metadata `interaction` del mensaje, mismo mecanismo que los quick replies de D-028) y el
widget la dibuja con campos y un boton. Lo que el usuario envia llega a
`POST /chat/conversations/{id}/handoff`, se valida AQUI (nunca se confia en el cliente,
security-guidance) y queda en el caso como un mensaje `FORM_RESPONSE` legible por el asesor.

Solo lo ve el usuario AUTENTICADO (D-031, 2026-09-05: el anonimo no deriva, se le invita a
crear cuenta). Campos: asunto y detalle; el correo unicamente si el JWT de VMC no lo trajo.
Un solo paso: los "dos pasos" de D-029 eran por los cinco campos del anonimo.

Modulo puro: sin DynamoDB ni FastAPI, para que el worker (que ofrece el formulario) y la API
(que lo valida) compartan la MISMA definicion sin importarse entre si.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Tipo de interaccion que el widget sabe dibujar como formulario.
HANDOFF_FORM = "HANDOFF_FORM"
HANDOFF_FORM_VERSION = 2

MAX_EMAIL_CHARS = 254
MAX_SUBJECT_CHARS = 120
MIN_SUBJECT_CHARS = 3
MIN_DETAIL_CHARS = 10

# Validacion deliberadamente laxa: rechaza lo que claramente no es un correo sin pelearse con
# formatos legitimos. Verificar que el correo EXISTE es trabajo del asesor.
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")


class FormValidationError(ValueError):
    """Un campo no pasa. `field` le dice al widget que casilla marcar."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field


@dataclass(frozen=True, slots=True)
class HandoffForm:
    subject: str
    detail: str
    email: str | None = None


def handoff_form_spec(*, needs_email: bool) -> dict:
    """La metadata del mensaje del bot que el widget dibuja como tarjeta de formulario. Todos
    los campos son obligatorios. Los `max` viajan para que el widget corte donde el servidor
    va a cortar; el servidor valida igual (el HTML se edita)."""
    fields: list[dict] = []
    if needs_email:
        fields.append(_field("email", "Correo", "email", max=MAX_EMAIL_CHARS))
    fields.append(_field("subject", "Asunto", "text", max=MAX_SUBJECT_CHARS))
    fields.append(_field("detail", "Cuéntanos qué pasó", "textarea", max=None))
    return {
        "interaction": {
            "type": HANDOFF_FORM,
            "version": HANDOFF_FORM_VERSION,
            "fields": fields,
            "submit": "Contactar",
        }
    }


def _field(name: str, label: str, kind: str, *, max: int | None) -> dict:
    spec = {"name": name, "label": label, "type": kind}
    if max is not None:
        spec["max"] = max
    return spec


def validate_handoff_form(
    form: HandoffForm, *, needs_email: bool, max_detail_chars: int
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
    email = _clean(form.email).lower() if form.email else ""
    if needs_email and not email:
        raise FormValidationError("email", "Necesitamos un correo para contactarte")
    if email and (len(email) > MAX_EMAIL_CHARS or not _EMAIL.match(email)):
        raise FormValidationError("email", "Ese correo no parece válido")
    return HandoffForm(subject=subject, detail=detail, email=email or None)


def summary_text(form: HandoffForm) -> str:
    """Contenido legible del mensaje FORM_RESPONSE: lo que ve el asesor en el caso (y el
    usuario como eco de lo que envio). El correo va solo si se pidio."""
    lines = [f"Asunto: {form.subject}", "", form.detail]
    if form.email:
        lines += ["", f"Correo: {form.email}"]
    return "\n".join(lines)


def _clean(value: str | None) -> str:
    # Colapsa espacios internos y quita controles: un campo de formulario es UNA linea, salvo
    # el detalle, donde los saltos de linea se respetan a proposito.
    if value is None:
        return ""
    return re.sub(r"[ \t]+", " ", value.replace("\r", "")).strip()
