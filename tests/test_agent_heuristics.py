"""Capa determinista del clasificador (backend/agent/heuristics.py) — RF-015/016.

Criterios derivados del spec que cubre cada bloque:
  AC-H1  peticion explicita de asesor o escalada -> ADVISOR sin llamada IA, con nombre de regla
  AC-H2  busqueda de vehiculos sin terminos de proceso -> CATALOG
  AC-H3  contexto de participacion/proceso aunque mencione vehiculos -> sin decision
  AC-H4  señales de frustracion de media confianza -> sin decision + frustration_hint
  AC-H5  mensajes neutros -> nada; ADVISOR gana sobre CATALOG

Son tests puros: no necesitan dynamodb-local ni mocks de IA, porque la capa existe
justamente para no llamar a la IA.
"""

import pytest

from backend.agent.heuristics import HeuristicResult, classify_by_rules, normalize
from backend.agent.intents import Intent

# ───────────────────────────────── AC-H1: ADVISOR ─────────────────────────────────


@pytest.mark.parametrize(
    ("message", "expected_rule"),
    [
        ("quiero hablar con un asesor por favor", "advisor_request"),
        ("pásame con alguien al toque", "advisor_request"),
        ("necesito que me atienda una persona real", "advisor_request"),
        ("NECESITO UN AGENTE", "advisor_request"),
        ("no quiero hablar con una máquina", "bot_rejection"),
        ("este bot no sirve", "bot_rejection"),
        ("a qué número llamo para hablar con ustedes", "voice_channel"),
        ("me voy a indecopi", "legal_threat"),
        ("quiero el libro de reclamaciones", "legal_threat"),
        ("son unos estafadores, están robando", "fraud_accusation"),
        ("pésimo servicio, me tienen harto", "hostility"),
        ("me estás floreando, no veo mi depósito", "peruvian_complaint"),
        ("perdí mi consignación y nadie responde", "funds_claim"),
        ("devuélvanme mi plata", "funds_claim"),
    ],
)
def test_peticion_explicita_o_escalada_deriva_a_asesor_sin_ia(message, expected_rule):
    result = classify_by_rules(message)

    assert result.intent is Intent.ADVISOR
    assert result.rule == expected_rule, "el motivo de derivacion viaja a AIUsage y al ticket"


@pytest.mark.parametrize(
    "message",
    [
        # Verbo y sustantivo presentes, pero "persona juridica/natural" es un concepto del
        # registro: el patron acotado no debe confundirlo con pedir una persona.
        "¿una persona jurídica puede registrarse?",
        "necesito saber si una persona natural puede participar",
        # Menciona al asesor como parte del proceso, no lo pide.
        "¿el asesor me llama después de ganar la subasta?",
        "¿cuál es el horario de atención al cliente?",
        "necesito ayuda para registrarme",
        # Pregunta de confianza, no acusacion: el bot responde con empatia (RF-017).
        "¿cómo sé que esto no es una estafa?",
    ],
)
def test_mencion_de_personas_o_confianza_no_deriva_a_asesor(message):
    assert classify_by_rules(message).intent is not Intent.ADVISOR


# ───────────────────────────────── AC-H2: CATALOG ─────────────────────────────────


@pytest.mark.parametrize(
    ("message", "expected_rule"),
    [
        ("¿tienen camionetas 4x4?", "catalog_search"),
        ("qué carros hay", "catalog_search"),
        ("hay unidades disponibles en arequipa?", "catalog_search"),
        ("busco un toyota yaris 2019", "catalog_make_or_model"),
        ("cuánto vale una hilux 2018", "catalog_make_or_model"),
    ],
)
def test_busqueda_de_vehiculos_va_al_catalogo_sin_ia(message, expected_rule):
    result = classify_by_rules(message)

    assert result.intent is Intent.CATALOG
    assert result.rule == expected_rule


# ─────────────────────── AC-H3: proceso mencionado -> no decide ───────────────────────


@pytest.mark.parametrize(
    "message",
    [
        # El caso que el proyecto de referencia clasificaba mal: ya encontro el carro y
        # pregunta por el proceso de participar.
        "quiero participar en un kia picanto que vi en su web",
        "¿hay que consignar para ver el carro?",
        "¿cuánto cuesta la comisión si gano un auto?",
        "¿puedo agendar una visita para la camioneta?",
        # "automático" contiene "auto": el limite de palabra evita el falso positivo.
        "¿hay algo automático en el proceso?",
    ],
)
def test_vehiculo_con_contexto_de_proceso_queda_para_haiku(message):
    assert classify_by_rules(message).intent is None


# ───────────────────────── AC-H4: señal de frustracion ─────────────────────────


@pytest.mark.parametrize(
    "message",
    [
        "ya van 3 veces que intento pujar y sale error de sesión",
        "QUIERO REGISTRARME YA!!!",
        "ok da igual, ya no quiero nada",
        "qué palta, no me carga la página de registro",
    ],
)
def test_frustracion_media_no_decide_pero_marca_la_señal(message):
    result = classify_by_rules(message)

    assert result.intent is None
    assert result.frustration_hint is True


def test_la_señal_de_frustracion_se_reporta_aunque_una_regla_decida():
    # El grito en mayusculas es señal de tono y ADVISOR decide por el sustantivo: ambas
    # cosas son ciertas y AIUsage debe poder registrarlas.
    result = classify_by_rules("NECESITO UN AGENTE")

    assert result.intent is Intent.ADVISOR
    assert result.frustration_hint is True


# ──────────────────────────── AC-H5: neutros y prioridad ────────────────────────────


@pytest.mark.parametrize("message", ["hola", "¿qué son los subascoins?", "gracias, ya entendí"])
def test_mensaje_neutro_no_decide_ni_marca_frustracion(message):
    assert classify_by_rules(message) == HeuristicResult(
        intent=None, rule=None, frustration_hint=False
    )


@pytest.mark.parametrize("message", ["", "   ", None])
def test_mensaje_vacio_no_decide(message):
    result = classify_by_rules(message)

    assert (result.intent, result.rule, result.frustration_hint) == (None, None, False)


def test_asesor_gana_sobre_catalogo_cuando_coexisten():
    result = classify_by_rules("¿tienen hilux? no me sirve este bot, pásame con alguien")

    assert result.intent is Intent.ADVISOR
    assert result.rule == "bot_rejection"


# ───────────────────────────────── normalizacion ─────────────────────────────────


def test_normalize_iguala_mayusculas_tildes_y_espacios():
    assert normalize("  PÁSAME   con  Él ") == "pasame con el"
    assert normalize("qué piña") == "que pina"
