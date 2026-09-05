"""Formulario de asesor (conversations/forms.py) — D-029 revisada por D-031, RF-024.

Criterios (puros, sin DynamoDB):
  AC-F1  la tarjeta pide asunto y detalle en UN paso, y el correo unicamente si la identidad
         de VMC no lo trajo; todos los campos son obligatorios
  AC-F2  la validacion normaliza (espacios, correo en minusculas) y rechaza con el campo
         culpable: asunto corto o largo, detalle corto o largo, correo mal formado o ausente
         cuando hace falta
  AC-F3  el resumen legible lleva asunto, detalle y el correo solo si se dio
"""

import pytest

from backend.conversations import forms
from backend.conversations.forms import FormValidationError, HandoffForm


def _campos(spec: dict) -> list[str]:
    return [f["name"] for f in spec["interaction"]["fields"]]


def test_la_tarjeta_pide_asunto_y_detalle_y_el_correo_solo_si_falta():
    con_correo = forms.handoff_form_spec(needs_email=False)
    assert con_correo["interaction"]["type"] == forms.HANDOFF_FORM
    assert _campos(con_correo) == ["subject", "detail"]
    assert forms.handoff_form_spec(needs_email=True)["interaction"]["fields"][0] == {
        "name": "email", "label": "Correo", "type": "email", "max": forms.MAX_EMAIL_CHARS
    }
    assert _campos(forms.handoff_form_spec(needs_email=True)) == ["email", "subject", "detail"]


def test_normaliza_y_acepta_un_formulario_valido():
    limpio = forms.validate_handoff_form(
        HandoffForm(
            subject="  Problema con   mi puja ",
            detail="  No me deja ofertar en la subasta de hoy.\nYa reintenté dos veces. ",
            email=" Ana@Example.TEST ",
        ),
        needs_email=True,
        max_detail_chars=500,
    )
    assert limpio.subject == "Problema con mi puja"
    assert limpio.detail == "No me deja ofertar en la subasta de hoy.\nYa reintenté dos veces."
    assert limpio.email == "ana@example.test"


@pytest.mark.parametrize(
    ("cambios", "campo"),
    [
        ({"subject": "ok"}, "subject"),
        ({"subject": "x" * 121}, "subject"),
        ({"detail": "corto"}, "detail"),
        ({"detail": "d" * 501}, "detail"),
        ({"email": ""}, "email"),
        ({"email": "no-es-correo"}, "email"),
    ],
)
def test_rechaza_con_el_campo_culpable(cambios, campo):
    base = {
        "subject": "Problema con mi puja",
        "detail": "No me deja ofertar en la subasta de hoy.",
        "email": "ana@example.test",
    }
    with pytest.raises(FormValidationError) as error:
        forms.validate_handoff_form(
            HandoffForm(**{**base, **cambios}), needs_email=True, max_detail_chars=500
        )
    assert error.value.field == campo


def test_con_correo_en_el_jwt_no_se_pide_ni_se_guarda():
    limpio = forms.validate_handoff_form(
        HandoffForm(subject="Consulta de saldo", detail="Quiero saber cuándo me devuelven."),
        needs_email=False,
        max_detail_chars=500,
    )
    assert limpio.email is None


def test_el_resumen_lleva_el_correo_solo_si_se_dio():
    con_correo = forms.summary_text(
        HandoffForm(subject="Asunto X", detail="Detalle Y", email="a@x.test")
    )
    assert con_correo == "Asunto: Asunto X\n\nDetalle Y\n\nCorreo: a@x.test"
    assert forms.summary_text(HandoffForm(subject="Asunto X", detail="Detalle Y")) == (
        "Asunto: Asunto X\n\nDetalle Y"
    )
