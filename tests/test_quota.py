"""Tope de ejecuciones de IA por actor — T-09 / D-027 (revisada 2026-09-01).

Criterios:
  AC-Q1  con los topes en 0 (dev) nada se frena y la tabla RateLimits ni se toca
  AC-Q2  el anonimo se agota por hora o por dia — la ventana que caiga primero
  AC-Q3  el autenticado tiene su propia cuota (el doble en prod) y su propio mensaje fijo
  AC-Q4  lo que no llama a un modelo NO gasta: triviales, reglas (pedir asesor deriva
         incluso agotado — es justo lo que promete el mensaje fijo) y ofrecer botones
  AC-Q5  resolver un paso de flujo SI gasta; agotado, el flujo queda esperando
  AC-Q6  la cuota por IP se comparte entre sesiones anonimas distintas (D-027)

El modelo se sustituye por un doble y el RAG se parchea: la cuota se decide ANTES de llamar
a nada — estos tests no tocan Gemini ni Pinecone.
"""

import uuid

import pytest
from boto3.dynamodb.conditions import Key

from backend.agent import prompts
from backend.conversations import repository
from backend.conversations.models import SenderType
from backend.core.config import reset_settings
from tests.helpers.scenario import (
    atiende,
    conversacion,
    escribe,
    ultima_respuesta,
)

pytestmark = pytest.mark.usefixtures("entorno_dynamo", "sin_rate_limit")


@pytest.fixture
def cuotas(monkeypatch):
    """Configura los topes por env (como en prod) y los limpia al salir."""

    def _set(anon_hour=0, anon_day=0, auth_hour=0, auth_day=0):
        monkeypatch.setenv("AI_QUOTA_ANON_PER_HOUR", str(anon_hour))
        monkeypatch.setenv("AI_QUOTA_ANON_PER_DAY", str(anon_day))
        monkeypatch.setenv("AI_QUOTA_AUTH_PER_HOUR", str(auth_hour))
        monkeypatch.setenv("AI_QUOTA_AUTH_PER_DAY", str(auth_day))
        reset_settings()

    yield _set
    reset_settings()


def preguntar(conversation, texto, ip_hash=None):
    """Escribe y atiende en un paso; devuelve el mensaje del usuario."""
    message = escribe(conversation, texto)
    atiende(message, ip_hash=ip_hash)
    return message


# Preguntas FAQ distintas entre si: repetir el mismo texto activaria el aviso de repetido
# (D-006) antes de llegar a la cuota, que es otra capa.
_PREGUNTAS = [
    "cuanto es la comision?",
    "como funciona la recarga?",
    "que es subaspass?",
    "como agendo una visita?",
]


# ─────────────────────────── AC-Q1: apagado (dev) = invisible ───────────────────────────


def test_con_topes_en_cero_nada_se_frena_ni_se_escribe(limpiar, tablas, fake_llm, con_rag):
    conversation = conversacion(limpiar, autenticada=False)
    for pregunta in _PREGUNTAS[:3]:
        preguntar(conversation, pregunta, ip_hash="hash-apagado")

    assert ultima_respuesta(conversation.conversation_id) == "Respuesta con evidencia."
    # Ni un contador escrito: en dev el pipeline no debe pagar latencia de una tabla extra.
    filas = tablas["rate_limits"].query(
        KeyConditionExpression=Key("limit_key").eq(
            f"SESSION#{conversation.conversation_id}"
        )
    )["Items"]
    assert filas == []


# ─────────────────────────── AC-Q2: el anonimo se agota ───────────────────────────


@pytest.mark.parametrize(
    ("anon_hour", "anon_day"),
    [(2, 0), (0, 2), (2, 5)],
    ids=["por_hora", "por_dia", "gana_la_ventana_corta"],
)
def test_el_anonimo_se_agota_en_la_ventana_que_caiga_primero(
    limpiar, tablas, fake_llm, con_rag, cuotas, anon_hour, anon_day
):
    cuotas(anon_hour=anon_hour, anon_day=anon_day)
    conversation = conversacion(limpiar, autenticada=False)

    preguntar(conversation, _PREGUNTAS[0], ip_hash="hash-" + uuid.uuid4().hex[:8])
    preguntar(conversation, _PREGUNTAS[1], ip_hash="hash-" + uuid.uuid4().hex[:8])
    llamadas_antes = len(fake_llm.calls)
    preguntar(conversation, _PREGUNTAS[2], ip_hash="hash-" + uuid.uuid4().hex[:8])

    assert ultima_respuesta(conversation.conversation_id) == (
        prompts.QUOTA_EXHAUSTED_ANON_RESPONSE
    )
    assert len(fake_llm.calls) == llamadas_antes, "agotado no debe llamar a ningun modelo"
    usos = tablas["ai_usage"].query(
        KeyConditionExpression=Key("conversation_id").eq(conversation.conversation_id)
    )["Items"]
    bloqueada = [u for u in usos if u["source"] == "quota:exhausted"]
    assert len(bloqueada) == 1
    assert bloqueada[0]["provider"] == "NONE" and bloqueada[0]["estimated_cost_usd"] == 0


# ─────────────────────── AC-Q3: el autenticado tiene su propia cuota ───────────────────────


def test_el_autenticado_usa_su_cuota_y_su_mensaje(limpiar, fake_llm, con_rag, cuotas):
    # Anonimo agotaria con 1; el autenticado tiene 2 (el doble, D-027 revisada).
    cuotas(anon_day=1, auth_day=2)
    conversation = conversacion(limpiar, autenticada=True)

    preguntar(conversation, _PREGUNTAS[0])
    preguntar(conversation, _PREGUNTAS[1])
    assert ultima_respuesta(conversation.conversation_id) == "Respuesta con evidencia."

    preguntar(conversation, _PREGUNTAS[2])
    assert ultima_respuesta(conversation.conversation_id) == (
        prompts.QUOTA_EXHAUSTED_AUTH_RESPONSE
    )


# ──────────────── AC-Q4: lo gratuito sigue vivo con la cuota agotada ────────────────


def test_pedir_asesor_ofrece_el_formulario_incluso_agotado(limpiar, fake_llm, con_rag, cuotas):
    """El mensaje fijo de cuota PROMETE que pedir asesor funciona: esa ruta la deciden las
    reglas (sin modelo), asi que no puede quedar detras del tope. Con D-029 "funciona"
    significa que el bot ofrece la tarjeta de formulario."""
    cuotas(auth_day=1)
    conversation = conversacion(limpiar, autenticada=True)
    preguntar(conversation, _PREGUNTAS[0])  # gasta la unica ejecucion

    preguntar(conversation, "quiero hablar con un asesor")

    del_bot = [
        m for m in repository.list_messages(conversation.conversation_id)
        if m.sender_type == SenderType.BOT
    ]
    assert del_bot[-1].content == prompts.HANDOFF_OFFER_RESPONSE
    assert (del_bot[-1].metadata or {}).get("interaction", {}).get("type") == "HANDOFF_FORM"


def test_un_trivial_no_gasta_cuota(limpiar, fake_llm, con_rag, cuotas):
    cuotas(anon_day=1)
    conversation = conversacion(limpiar, autenticada=False)

    preguntar(conversation, "hola")  # trivial: fijo, sin modelo, sin gasto
    preguntar(conversation, _PREGUNTAS[0])

    assert ultima_respuesta(conversation.conversation_id) == "Respuesta con evidencia."


# ─────────────── AC-Q5: flujos — ofrecer gratis, resolver paga, agotado espera ───────────────


def test_ofrecer_botones_es_gratis_y_resolver_gasta(limpiar, fake_llm, con_rag, cuotas):
    cuotas(anon_day=1)
    conversation = conversacion(limpiar, autenticada=False)

    preguntar(conversation, "quiero participar")  # botones: gratis
    preguntar(conversation, "en vivo")  # resuelve: gasta la unica ejecucion
    assert ultima_respuesta(conversation.conversation_id) == "Respuesta con evidencia."

    preguntar(conversation, _PREGUNTAS[0])
    assert ultima_respuesta(conversation.conversation_id) == (
        prompts.QUOTA_EXHAUSTED_ANON_RESPONSE
    )


def test_agotado_el_flujo_queda_esperando(limpiar, fake_llm, con_rag, cuotas):
    """Resolver el paso llama al redactor (pagado): agotado, sale el mensaje fijo pero el
    flujo NO se pierde — al renovarse la cuota, "en vivo" escrito lo resuelve igual."""
    cuotas(anon_day=1)
    conversation = conversacion(limpiar, autenticada=False)
    preguntar(conversation, _PREGUNTAS[0])  # gasta la unica ejecucion

    preguntar(conversation, "quiero participar")  # botones: gratis, funciona igual
    actual = repository.get_conversation(conversation.conversation_id)
    assert actual.active_flow == "PARTICIPATION"

    preguntar(conversation, "en vivo")  # resolver necesitaria el redactor -> fijo de cuota
    assert ultima_respuesta(conversation.conversation_id) == (
        prompts.QUOTA_EXHAUSTED_ANON_RESPONSE
    )
    actual = repository.get_conversation(conversation.conversation_id)
    assert actual.active_flow == "PARTICIPATION", "el flujo espera a que la cuota se renueve"


# ─────────────────── AC-Q6: la IP comparte cuota entre sesiones anonimas ───────────────────


def test_la_misma_ip_comparte_cuota_entre_sesiones(limpiar, fake_llm, con_rag, cuotas):
    cuotas(anon_day=1)
    ip = "ip-compartida-" + uuid.uuid4().hex[:8]

    primera = conversacion(limpiar, autenticada=False)
    preguntar(primera, _PREGUNTAS[0], ip_hash=ip)
    assert ultima_respuesta(primera.conversation_id) == "Respuesta con evidencia."

    # Sesion nueva (otra pestana del mismo actor): el contador de IP ya esta agotado.
    segunda = conversacion(limpiar, autenticada=False)
    preguntar(segunda, _PREGUNTAS[1], ip_hash=ip)
    assert ultima_respuesta(segunda.conversation_id) == prompts.QUOTA_EXHAUSTED_ANON_RESPONSE


def test_sin_ip_cada_sesion_anonima_cuenta_por_su_lado(limpiar, fake_llm, con_rag, cuotas):
    """CGNAT y proxies pueden dejar la IP inservible; sin hash de IP queda el contador por
    sesion, que es la otra pata de D-027 — nunca cero frenos."""
    cuotas(anon_day=1)

    primera = conversacion(limpiar, autenticada=False)
    preguntar(primera, _PREGUNTAS[0])
    segunda = conversacion(limpiar, autenticada=False)
    preguntar(segunda, _PREGUNTAS[1])

    assert ultima_respuesta(segunda.conversation_id) == "Respuesta con evidencia."
    preguntar(segunda, _PREGUNTAS[2])
    assert ultima_respuesta(segunda.conversation_id) == prompts.QUOTA_EXHAUSTED_ANON_RESPONSE
