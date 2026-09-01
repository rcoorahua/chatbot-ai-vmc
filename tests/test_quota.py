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
from backend.agent.rag import Fragment, RagResult
from backend.conversations import repository, service
from backend.conversations.models import SenderType
from backend.core import llm
from backend.core.auth import VmcIdentity
from backend.core.config import reset_settings
from backend.core.jobs import AIJob
from backend.workers import ai_worker

pytestmark = pytest.mark.usefixtures("entorno_dynamo")


@pytest.fixture(autouse=True)
def _sin_rate_limit(monkeypatch):
    """Aqui se prueba la cuota diaria/horaria (D-027), no el limite por minuto (D-005)."""
    monkeypatch.setenv("MAX_MESSAGES_PER_MINUTE", "0")
    reset_settings()
    yield
    reset_settings()


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


@pytest.fixture
def limpiar(tablas):
    ids: list[str] = []
    yield ids.append
    for conversation_id in ids:
        for tabla, sk in (("messages", "message_key"), ("ai_usage", "execution_key")):
            for item in tablas[tabla].query(
                KeyConditionExpression=Key("conversation_id").eq(conversation_id)
            )["Items"]:
                tablas[tabla].delete_item(
                    Key={"conversation_id": conversation_id, sk: item[sk]}
                )
        tablas["conversations"].delete_item(Key={"conversation_id": conversation_id})


class FakeLLM:
    def __init__(self):
        self.calls: list[dict] = []

    def generate(self, *, tier, system, messages, max_output_tokens, temperature=None):
        self.calls.append({"tier": tier})
        text = "<intent>FAQ</intent>" if tier == llm.ModelTier.FAST else "Respuesta con evidencia."
        return llm.LLMResponse(
            text=text, model=llm.model_for(tier).name, tier=tier,
            usage={"input": 100, "output": 10, "cached_read": 0, "cached_creation": 0},
            latency_ms=10,
        )


@pytest.fixture
def fake_llm(monkeypatch):
    fake = FakeLLM()
    monkeypatch.setattr("backend.agent.classifier.get_client", lambda: fake)
    monkeypatch.setattr("backend.agent.writer.get_client", lambda: fake)
    return fake


@pytest.fixture
def con_rag(monkeypatch):
    fragmento = Fragment(text="La comision es 3.9%.", topic="Comision", score=0.9)
    monkeypatch.setattr(
        ai_worker.rag, "retrieve",
        lambda text, **kwargs: RagResult(relevant=[fragmento], discarded=[], threshold=0.84),
    )
    return fragmento


def _conversacion(limpiar, *, autenticada=False):
    identity = (
        VmcIdentity(user_id="vmc_" + uuid.uuid4().hex[:8], name="Aaron") if autenticada else None
    )
    conversation, _ = service.open_conversation(identity)
    limpiar(conversation.conversation_id)
    return conversation


def _atiende(conversation, texto, ip_hash=None):
    message, _ = service.post_user_message(
        conversation, client_message_id="cli-" + uuid.uuid4().hex, content=texto
    )
    ai_worker._process(
        AIJob(
            conversation_id=conversation.conversation_id,
            message_id=message.message_id,
            message_key=message.message_key,
            requested_at=message.created_at,
            ip_hash=ip_hash,
        ).model_dump_json()
    )
    return message


def _ultima_respuesta(conversation_id):
    bots = [
        m for m in repository.list_messages(conversation_id)
        if m.sender_type == SenderType.BOT
    ]
    return bots[-1].content if bots else None


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
    conversation = _conversacion(limpiar)
    for pregunta in _PREGUNTAS[:3]:
        _atiende(conversation, pregunta, ip_hash="hash-apagado")

    assert _ultima_respuesta(conversation.conversation_id) == "Respuesta con evidencia."
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
    conversation = _conversacion(limpiar)

    _atiende(conversation, _PREGUNTAS[0], ip_hash="hash-" + uuid.uuid4().hex[:8])
    _atiende(conversation, _PREGUNTAS[1], ip_hash="hash-" + uuid.uuid4().hex[:8])
    llamadas_antes = len(fake_llm.calls)
    _atiende(conversation, _PREGUNTAS[2], ip_hash="hash-" + uuid.uuid4().hex[:8])

    assert _ultima_respuesta(conversation.conversation_id) == (
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
    conversation = _conversacion(limpiar, autenticada=True)

    _atiende(conversation, _PREGUNTAS[0])
    _atiende(conversation, _PREGUNTAS[1])
    assert _ultima_respuesta(conversation.conversation_id) == "Respuesta con evidencia."

    _atiende(conversation, _PREGUNTAS[2])
    assert _ultima_respuesta(conversation.conversation_id) == (
        prompts.QUOTA_EXHAUSTED_AUTH_RESPONSE
    )


# ──────────────── AC-Q4: lo gratuito sigue vivo con la cuota agotada ────────────────


def test_pedir_asesor_deriva_incluso_agotado(limpiar, fake_llm, con_rag, cuotas):
    """El mensaje fijo de cuota PROMETE que pedir asesor funciona: esa ruta la deciden las
    reglas (sin modelo), asi que no puede quedar detras del tope."""
    cuotas(auth_day=1)
    conversation = _conversacion(limpiar, autenticada=True)
    _atiende(conversation, _PREGUNTAS[0])  # gasta la unica ejecucion

    _atiende(conversation, "quiero hablar con un asesor")

    actual = repository.get_conversation(conversation.conversation_id)
    assert str(actual.status) == "PENDING_ADVISOR" and actual.bot_enabled is False


def test_un_trivial_no_gasta_cuota(limpiar, fake_llm, con_rag, cuotas):
    cuotas(anon_day=1)
    conversation = _conversacion(limpiar)

    _atiende(conversation, "hola")  # trivial: fijo, sin modelo, sin gasto
    _atiende(conversation, _PREGUNTAS[0])

    assert _ultima_respuesta(conversation.conversation_id) == "Respuesta con evidencia."


# ─────────────── AC-Q5: flujos — ofrecer gratis, resolver paga, agotado espera ───────────────


def test_ofrecer_botones_es_gratis_y_resolver_gasta(limpiar, fake_llm, con_rag, cuotas):
    cuotas(anon_day=1)
    conversation = _conversacion(limpiar)

    _atiende(conversation, "quiero participar")  # botones: gratis
    _atiende(conversation, "en vivo")  # resuelve: gasta la unica ejecucion
    assert _ultima_respuesta(conversation.conversation_id) == "Respuesta con evidencia."

    _atiende(conversation, _PREGUNTAS[0])
    assert _ultima_respuesta(conversation.conversation_id) == (
        prompts.QUOTA_EXHAUSTED_ANON_RESPONSE
    )


def test_agotado_el_flujo_queda_esperando(limpiar, fake_llm, con_rag, cuotas):
    """Resolver el paso llama al redactor (pagado): agotado, sale el mensaje fijo pero el
    flujo NO se pierde — al renovarse la cuota, "en vivo" escrito lo resuelve igual."""
    cuotas(anon_day=1)
    conversation = _conversacion(limpiar)
    _atiende(conversation, _PREGUNTAS[0])  # gasta la unica ejecucion

    _atiende(conversation, "quiero participar")  # botones: gratis, funciona igual
    actual = repository.get_conversation(conversation.conversation_id)
    assert actual.active_flow == "PARTICIPATION"

    _atiende(conversation, "en vivo")  # resolver necesitaria el redactor -> fijo de cuota
    assert _ultima_respuesta(conversation.conversation_id) == (
        prompts.QUOTA_EXHAUSTED_ANON_RESPONSE
    )
    actual = repository.get_conversation(conversation.conversation_id)
    assert actual.active_flow == "PARTICIPATION", "el flujo espera a que la cuota se renueve"


# ─────────────────── AC-Q6: la IP comparte cuota entre sesiones anonimas ───────────────────


def test_la_misma_ip_comparte_cuota_entre_sesiones(limpiar, fake_llm, con_rag, cuotas):
    cuotas(anon_day=1)
    ip = "ip-compartida-" + uuid.uuid4().hex[:8]

    primera = _conversacion(limpiar)
    _atiende(primera, _PREGUNTAS[0], ip_hash=ip)
    assert _ultima_respuesta(primera.conversation_id) == "Respuesta con evidencia."

    # Sesion nueva (otra pestana del mismo actor): el contador de IP ya esta agotado.
    segunda = _conversacion(limpiar)
    _atiende(segunda, _PREGUNTAS[1], ip_hash=ip)
    assert _ultima_respuesta(segunda.conversation_id) == prompts.QUOTA_EXHAUSTED_ANON_RESPONSE


def test_sin_ip_cada_sesion_anonima_cuenta_por_su_lado(limpiar, fake_llm, con_rag, cuotas):
    """CGNAT y proxies pueden dejar la IP inservible; sin hash de IP queda el contador por
    sesion, que es la otra pata de D-027 — nunca cero frenos."""
    cuotas(anon_day=1)

    primera = _conversacion(limpiar)
    _atiende(primera, _PREGUNTAS[0])
    segunda = _conversacion(limpiar)
    _atiende(segunda, _PREGUNTAS[1])

    assert _ultima_respuesta(segunda.conversation_id) == "Respuesta con evidencia."
    _atiende(segunda, _PREGUNTAS[2])
    assert _ultima_respuesta(segunda.conversation_id) == prompts.QUOTA_EXHAUSTED_ANON_RESPONSE
