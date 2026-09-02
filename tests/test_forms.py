"""Formulario de handoff (conversations/forms.py) — D-029, RF-003, RF-024.

Criterios (puros, sin DynamoDB):
  AC-F1  la tarjeta pide nombre, correo y telefono (opcional) al anonimo; al autenticado solo
         asunto y detalle, y el correo unicamente si su identidad no lo trajo
  AC-F2  la validacion normaliza (espacios, correo en minusculas) y rechaza con el campo
         culpable: asunto corto, detalle corto o largo, correo o telefono mal formados,
         nombre/correo ausentes cuando son obligatorios
  AC-F3  el resumen legible lleva asunto, detalle y solo los datos de contacto que se dieron
"""

import pytest

from backend.conversations import forms
from backend.conversations.forms import FormValidationError, HandoffForm


def _campos(spec: dict) -> list[str]:
    return [f["name"] for f in spec["interaction"]["fields"]]


def _pasos(spec: dict) -> dict[int, list[str]]:
    """{paso: [campos]} — el agrupamiento que el widget usa para dibujar el asistente."""
    agrupado: dict[int, list[str]] = {}
    for field in spec["interaction"]["fields"]:
        agrupado.setdefault(field["step"], []).append(field["name"])
    return agrupado


def test_el_formulario_se_pide_en_dos_pasos_contacto_y_caso():
    """Cinco campos de golpe dentro de una burbuja se leen como un trámite. El servidor dice
    en qué paso va cada uno; el widget no lo adivina por el nombre."""
    assert _pasos(forms.handoff_form_spec(anonymous=True, needs_email=False)) == {
        forms.STEP_CONTACT: ["name", "email", "phone"],
        forms.STEP_CASE: ["subject", "detail"],
    }


def test_el_autenticado_con_correo_tiene_un_solo_paso():
    """Sin datos de contacto que pedir, el paso 1 se queda vacío y el widget dibuja una sola
    pantalla: anunciar "paso 1 de 2" para un recorrido que no existe sería mentir."""
    pasos = _pasos(forms.handoff_form_spec(anonymous=False, needs_email=False))
    assert pasos == {forms.STEP_CASE: ["subject", "detail"]}


def test_al_autenticado_sin_correo_se_le_pide_en_el_paso_de_contacto():
    pasos = _pasos(forms.handoff_form_spec(anonymous=False, needs_email=True))
    assert pasos[forms.STEP_CONTACT] == ["email"]
    assert pasos[forms.STEP_CASE] == ["subject", "detail"]


def test_la_tarjeta_pide_contacto_solo_al_anonimo():
    anon = forms.handoff_form_spec(anonymous=True, needs_email=False)
    assert anon["interaction"]["type"] == forms.HANDOFF_FORM
    assert _campos(anon) == ["name", "email", "phone", "subject", "detail"]
    por_campo = {f["name"]: f for f in anon["interaction"]["fields"]}
    assert por_campo["phone"]["required"] is False and por_campo["email"]["required"] is True

    auth = forms.handoff_form_spec(anonymous=False, needs_email=False)
    assert _campos(auth) == ["subject", "detail"]

    sin_correo = forms.handoff_form_spec(anonymous=False, needs_email=True)
    assert _campos(sin_correo) == ["email", "subject", "detail"]


def test_normaliza_y_acepta_un_formulario_valido():
    limpio = forms.validate_handoff_form(
        HandoffForm(
            subject="  Problema con   mi puja ",
            detail="  No me deja ofertar en la subasta de hoy.\nYa reintenté dos veces. ",
            name=" Ana  Torres ",
            email=" Ana@Example.TEST ",
            phone=" +51 999 888 777 ",
        ),
        anonymous=True,
        needs_email=False,
        max_detail_chars=500,
    )
    assert limpio.subject == "Problema con mi puja"
    assert limpio.detail == "No me deja ofertar en la subasta de hoy.\nYa reintenté dos veces."
    assert limpio.name == "Ana Torres"
    assert limpio.email == "ana@example.test"
    assert limpio.phone == "+51 999 888 777"


@pytest.mark.parametrize(
    ("cambios", "campo"),
    [
        ({"subject": "ok"}, "subject"),
        ({"subject": "x" * 121}, "subject"),
        ({"detail": "corto"}, "detail"),
        ({"detail": "d" * 501}, "detail"),
        ({"name": ""}, "name"),
        ({"email": ""}, "email"),
        ({"email": "no-es-correo"}, "email"),
        ({"phone": "abc"}, "phone"),
    ],
)
def test_rechaza_con_el_campo_culpable(cambios, campo):
    base = {
        "subject": "Problema con mi puja",
        "detail": "No me deja ofertar en la subasta de hoy.",
        "name": "Ana",
        "email": "ana@example.test",
        "phone": None,
    }
    with pytest.raises(FormValidationError) as error:
        forms.validate_handoff_form(
            HandoffForm(**{**base, **cambios}),
            anonymous=True,
            needs_email=False,
            max_detail_chars=500,
        )
    assert error.value.field == campo


def test_el_autenticado_con_correo_no_necesita_contacto():
    limpio = forms.validate_handoff_form(
        HandoffForm(subject="Consulta de saldo", detail="Quiero saber cuándo me devuelven."),
        anonymous=False,
        needs_email=False,
        max_detail_chars=500,
    )
    assert limpio.name is None and limpio.email is None and limpio.phone is None


def test_el_autenticado_sin_correo_en_el_jwt_debe_darlo():
    with pytest.raises(FormValidationError) as error:
        forms.validate_handoff_form(
            HandoffForm(subject="Consulta de saldo", detail="Quiero saber cuándo me devuelven."),
            anonymous=False,
            needs_email=True,
            max_detail_chars=500,
        )
    assert error.value.field == "email"


def test_el_resumen_lleva_solo_el_contacto_que_se_dio():
    con_contacto = forms.summary_text(
        HandoffForm(subject="Asunto X", detail="Detalle Y", name="Ana", email="a@x.test")
    )
    assert con_contacto == "Asunto: Asunto X\n\nDetalle Y\n\nNombre: Ana\nCorreo: a@x.test"
    sin_contacto = forms.summary_text(HandoffForm(subject="Asunto X", detail="Detalle Y"))
    assert sin_contacto == "Asunto: Asunto X\n\nDetalle Y"
