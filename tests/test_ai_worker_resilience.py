"""El bot cuando Gemini NO responde, y los flujos tras descartar la confirmacion de asesor.

Sesion real del 2026-09-03 (Aaron, con la cuota gratuita de Gemini agotada por una bateria
previa): cada turno terminaba en "No tengo ese dato a la mano" con el RAG trayendo 4/4 sobre
el umbral (0.913), y la consola decia solo "Fallback (sin modelo)" sin la causa. Dos defectos:

  AC-R1  con evidencia y el modelo caido, el bot NO dice "no tengo ese dato" (es falso): admite
         que no esta disponible, invita a reintentar y ofrece el asesor con los botones si/no
  AC-R2  la causa queda registrada: AIUsage con status=ERROR y `error` (familia + codigo),
         tanto en la clasificacion como en la respuesta, y `source=model_unavailable`
  AC-R3  `LLMError.kind` separa cuota (429 fatal), rate limit (429), timeout NUESTRO
         (sin codigo), 5xx del proveedor y credencial — la consola no debe confundirlos
  AC-R4  si el usuario ignora "¿quieres un asesor?" y escribe un disparador de flujo, el
         flujo se ofrece (antes se saltaba la deteccion y caia al RAG con el texto literal)
  AC-R5  un flujo vencido + un disparador nuevo ofrece los botones, no silencio (la fila se
         relee tras limpiar: la version cambio)

Contra dynamodb-local real, con modelo e indice sustituidos por dobles.
"""

from datetime import timedelta

import pytest

from backend.agent import flows, prompts
from backend.agent.rag import Fragment, RagResult
from backend.conversations import repository
from backend.core import llm
from backend.core.clock import to_iso, utc_now
from backend.workers import ai_worker
from tests.helpers.fakes import FakeLLM, install_llm
from tests.helpers.scenario import atiende, conversacion, escribe, fresca, respuestas_bot, usos_de

pytestmark = pytest.mark.usefixtures("entorno_dynamo", "sin_rate_limit")


QUOTA_MESSAGE = (
    "You exceeded your current quota, please check your plan and billing details. "
    "Quota exceeded for metric: generate_content_free_tier_requests, limit: 20"
)


@pytest.fixture
def gemini_caido(monkeypatch):
    """Gemini con la cuota agotada: rechaza TODO al instante con 429 (el caso real)."""
    error = llm.LLMError(QUOTA_MESSAGE, provider="gemini", status_code=429, is_fatal=True)
    return install_llm(monkeypatch, FakeLLM(error=error))


@pytest.fixture
def gemini_vivo(monkeypatch):
    return install_llm(monkeypatch, FakeLLM(answer="Respuesta con evidencia."))


HIT = Fragment(text="Paso 1: ingresa a vmcsubastas.com.", topic="Registro", score=0.913)
BAJO = Fragment(text="otra cosa", topic="Otro", score=0.79)
CON = RagResult(relevant=[HIT], discarded=[], threshold=0.84)
SIN = RagResult(relevant=[], discarded=[BAJO], threshold=0.84)


@pytest.fixture
def con_evidencia(monkeypatch):
    monkeypatch.setattr(ai_worker.rag, "retrieve", lambda text, **kwargs: CON)
    return HIT


@pytest.fixture
def sin_evidencia(monkeypatch):
    monkeypatch.setattr(ai_worker.rag, "retrieve", lambda text, **kwargs: SIN)
    return BAJO


@pytest.fixture
def indice_por_tema(monkeypatch):
    """Evidencia solo para el corpus: "placas en marte" no recupera nada; "comision" si."""
    monkeypatch.setattr(
        ai_worker.rag, "retrieve",
        lambda text, **kwargs: CON if "comision" in text.lower() else SIN,
    )


# ───────────────────── AC-R1 / AC-R2: modelo caido, evidencia presente ─────────────────────


def test_con_evidencia_y_gemini_caido_el_bot_admite_que_no_esta_disponible(
    limpiar, gemini_caido, con_evidencia, tablas
):
    conversation = conversacion(limpiar)
    atiende(escribe(conversation, "quiero registrarme"))

    ultima = respuestas_bot(conversation.conversation_id)[-1]
    assert ultima.content == prompts.MODEL_UNAVAILABLE_CONFIRM_RESPONSE
    assert prompts.FAQ_NO_EVIDENCE_CONFIRM_RESPONSE not in [
        m.content for m in respuestas_bot(conversation.conversation_id)
    ], "el dato existe: no puede decir que no lo tiene"
    # Con los botones si/no del asesor, como cualquier confirmacion.
    assert ultima.metadata["interaction"]["flow"] == flows.HANDOFF_CONFIRM

    usos = usos_de(tablas, conversation.conversation_id)
    clasificacion = next(u for u in usos if u["execution_type"] == "CLASSIFICATION")
    respuesta = next(u for u in usos if u["source"] == "model_unavailable")
    assert clasificacion["status"] == "ERROR" and clasificacion["error"].startswith("quota 429")
    assert respuesta["status"] == "ERROR" and respuesta["error"].startswith("quota 429")
    assert respuesta["rag_used"] is True
    assert len(gemini_caido.calls) == 2, "clasificador y redactor, una vez cada uno (sin respaldo)"


def test_sin_evidencia_y_gemini_caido_sigue_siendo_no_tengo_ese_dato(
    limpiar, gemini_caido, sin_evidencia
):
    """Sin fragmentos el redactor ni se llama: aqui si es "no tengo ese dato"."""
    conversation = conversacion(limpiar)
    atiende(escribe(conversation, "cuanto cuesta tramitar placas en marte"))
    assert respuestas_bot(conversation.conversation_id)[-1].content == (
        prompts.FAQ_NO_EVIDENCE_CONFIRM_RESPONSE
    )


def test_con_gemini_vivo_no_hay_error_registrado(limpiar, gemini_vivo, con_evidencia, tablas):
    conversation = conversacion(limpiar)
    atiende(escribe(conversation, "quiero registrarme"))
    assert all(u["status"] == "SUCCESS" and "error" not in u
               for u in usos_de(tablas, conversation.conversation_id))


# ───────────────────────── AC-R3: familias de error ─────────────────────────


@pytest.mark.parametrize(
    ("kwargs", "kind"),
    [
        ({"status_code": 429, "is_fatal": True}, "quota"),
        ({"status_code": 429, "is_rate_limit": True}, "rate_limit"),
        ({"status_code": 401, "is_fatal": True}, "auth"),
        ({"status_code": 504, "is_connection": True}, "provider"),
        ({"status_code": 503, "is_connection": True}, "provider"),
    ],
)
def test_llm_error_kind_por_codigo(kwargs, kind):
    error = llm.LLMError("x", provider="gemini", **kwargs)
    assert error.kind == kind
    assert error.describe().startswith(f"{kind} {kwargs['status_code']}: ")


def test_el_timeout_nuestro_se_distingue_del_deadline_de_gemini():
    """La duda de Aaron (2026-09-03): ¿fue Gemini o fue nuestro tope? Cada uno con su nombre."""
    nuestro = llm.LLMError(
        "ReadTimeout: The read operation timed out", provider="gemini", is_connection=True
    )
    de_gemini = llm.LLMError(
        "Deadline expired before operation could complete.", provider="gemini",
        status_code=504, is_connection=True,
    )
    assert nuestro.kind == "client_timeout"
    assert de_gemini.kind == "provider"
    assert nuestro.describe().startswith("client_timeout: ReadTimeout")


def test_describe_es_corto_y_de_una_linea():
    largo = llm.LLMError("linea 1\n  * linea 2\n" + "x" * 500, provider="gemini",
                         status_code=429, is_fatal=True)
    texto = largo.describe()
    assert "\n" not in texto and len(texto) < 200


# ───────────── AC-R4: descartar la confirmacion no se salta la deteccion de flujos ─────────────


def test_tras_ignorar_el_si_no_un_disparador_ofrece_su_flujo(
    limpiar, gemini_vivo, sin_evidencia
):
    """Sesion real: "no tengo ese dato, ¿asesor?" → "quiero participar" iba al clasificador y
    al RAG con el texto literal (0/4) → otra vez "no tengo ese dato, ¿asesor?". En bucle."""
    conversation = conversacion(limpiar)
    atiende(escribe(conversation, "cuanto cuesta tramitar placas en marte"))
    assert fresca(conversation).active_flow == flows.HANDOFF_CONFIRM
    llamadas = len(gemini_vivo.calls)

    atiende(escribe(fresca(conversation), "quiero participar"))

    ultima = respuestas_bot(conversation.conversation_id)[-1]
    assert ultima.metadata["interaction"]["flow"] == "PARTICIPATION"
    assert fresca(conversation).active_flow == "PARTICIPATION"
    assert len(gemini_vivo.calls) == llamadas, "ofrecer botones no llama a ningun modelo"


def test_tras_ignorar_el_si_no_una_pregunta_normal_sigue_el_pipeline(
    limpiar, gemini_vivo, indice_por_tema
):
    conversation = conversacion(limpiar)
    atiende(escribe(conversation, "cuanto cuesta tramitar placas en marte"))
    assert fresca(conversation).active_flow == flows.HANDOFF_CONFIRM

    atiende(escribe(fresca(conversation), "mejor dime cuanto es la comision"))

    assert respuestas_bot(conversation.conversation_id)[-1].content == gemini_vivo.answer
    assert fresca(conversation).active_flow is None


# ───────────────────── AC-R5: flujo vencido + disparador nuevo ─────────────────────


def test_un_flujo_vencido_mas_un_disparador_ofrece_los_botones(limpiar, gemini_vivo):
    conversation = conversacion(limpiar)
    atiende(escribe(conversation, "quiero consignar"))
    current = fresca(conversation)
    assert current.active_flow == "CONSIGNMENT"
    # Se vence a mano: la fecha de expiracion queda en el pasado.
    repository.set_flow_state(
        current.conversation_id, flow="CONSIGNMENT", step="SELECT_OFFER_TYPE", slots={},
        expires_at=to_iso(utc_now() - timedelta(hours=1)),
        expected_version=current.flow_version,
    )

    atiende(escribe(fresca(conversation), "quiero participar"))

    respuestas = respuestas_bot(conversation.conversation_id)
    assert len(respuestas) == 2, "antes: silencio (la transicion perdia la carrera de version)"
    assert respuestas[-1].metadata["interaction"]["flow"] == "PARTICIPATION"
    assert fresca(conversation).active_flow == "PARTICIPATION"
