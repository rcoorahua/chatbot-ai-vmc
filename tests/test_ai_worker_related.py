"""Respuesta completa + fuentes + preguntas hermanas + estado de cuenta en el worker (D-030,
2026-09-03). Contra dynamodb-local real, con el modelo y el indice sustituidos por dobles: se
prueba la orquestacion, no Gemini ni Pinecone.

Reproduce la conversacion real del 2026-09-03 (Aaron): "¿Como me registro en VMC?" costo
4 llamadas al redactor (paso a paso, un "si" por paso, ~1.900 tokens de entrada cada una) y
"¿Puedo registrarme como persona juridica?" se guardo la advertencia de la factura para un
turno siguiente. Ahora la respuesta va entera, la fuente como chip y las otras preguntas del
articulo como botones que van al RAG sin clasificador.

Criterios:
  AC-W1  una respuesta con evidencia lleva en metadata `sources` (chip) y los botones
         RELATED_QUESTIONS con las otras preguntas del articulo (sin la respondida, sin la
         introduccion, sin otros articulos)
  AC-W2  el clic en un boton busca con ESA pregunta, no llama al clasificador y queda en
         AIUsage como `related:model`
  AC-W3  un clic que no corresponde a los botones del ultimo mensaje del bot se degrada a
         texto normal (pasa por el clasificador)
  AC-W4  el redactor recibe el estado de cuenta: anonimo = sin cuenta, autenticado = con
         cuenta; nunca se lo pregunta al usuario
  AC-W5  como la respuesta ya no termina preguntando, un "ok" despues es el cierre trivial
"""

import uuid

import pytest
from boto3.dynamodb.conditions import Key

from backend.agent import prompts, related
from backend.agent.rag import Fragment, RagResult
from backend.conversations import repository, service
from backend.conversations.models import SenderType
from backend.core import llm
from backend.core.auth import VmcIdentity
from backend.core.config import reset_settings
from backend.core.jobs import AIJob
from backend.workers import ai_worker

pytestmark = pytest.mark.usefixtures("entorno_dynamo")

REG = "¡Registrarte es fácil y rápido!"
REG_URL = "https://ayuda.vmc.test/registro"
COMO = "¿Cómo me registro?"
PJ = "¿Puedo registrarme como persona jurídica?"
CLAVE = "He olvidado mi contraseña, ¿cómo puedo recuperar el ingreso a mi cuenta?"
RESPUESTA = "Para registrarte entra a vmcsubastas.com y dale a Regístrate 🙂"


def _frag(topic, question, score, url=REG_URL, sibling=False):
    return Fragment(text=f"{topic}\n{question}\nrespuesta.", topic=topic, source_url=url,
                    score=score, sibling=sibling)


@pytest.fixture
def limpiar(tablas):
    ids: list[str] = []
    yield ids.append
    for conversation_id in ids:
        for tabla, sk in (("messages", "message_key"), ("ai_usage", "execution_key")):
            for item in tablas[tabla].query(
                KeyConditionExpression=Key("conversation_id").eq(conversation_id)
            )["Items"]:
                tablas[tabla].delete_item(Key={"conversation_id": conversation_id, sk: item[sk]})
        tablas["conversations"].delete_item(Key={"conversation_id": conversation_id})


@pytest.fixture(autouse=True)
def _sin_rate_limit(monkeypatch):
    monkeypatch.setenv("MAX_MESSAGES_PER_MINUTE", "0")
    reset_settings()
    yield
    reset_settings()


class FakeLLM:
    def __init__(self):
        self.calls: list[dict] = []
        self.answer = RESPUESTA

    def generate(self, *, tier, system, messages, max_output_tokens, temperature=None):
        self.calls.append({"tier": tier, "system": system, "messages": messages})
        text = "<intent>FAQ</intent>" if tier == llm.ModelTier.FAST else self.answer
        return llm.LLMResponse(
            text=text, model=llm.model_for(tier).name, tier=tier,
            usage={"input": 100, "output": 10, "cached_read": 0, "cached_creation": 0},
            latency_ms=50,
        )

    def answer_calls(self):
        return [c for c in self.calls if c["tier"] == llm.ModelTier.ANSWER]

    def classify_calls(self):
        return [c for c in self.calls if c["tier"] == llm.ModelTier.FAST]


@pytest.fixture
def modelo(monkeypatch):
    fake = FakeLLM()
    monkeypatch.setattr("backend.agent.classifier.get_client", lambda: fake)
    monkeypatch.setattr("backend.agent.writer.get_client", lambda: fake)
    return fake


@pytest.fixture
def indice(monkeypatch, request):
    """Doble del indice: el articulo de registro con sus preguntas, mas un hit de otro
    articulo bajo el umbral. Registra cada consulta que recibe. Con `indirect` se le pasan
    los scores de COMO y PJ, para reproducir el orden que dio el indice real."""
    consultas: list[str] = []
    scores = getattr(request, "param", {"como": 0.875, "pj": 0.87})

    def buscar(text, **kwargs):
        consultas.append(text)
        if "registr" not in text.lower():
            return RagResult(relevant=[], discarded=[], threshold=0.84)
        relevant = sorted([
            _frag(REG, COMO, scores["como"]),
            _frag(REG, PJ, scores["pj"], sibling=True),
            _frag(REG, "Para registrarte, ingresa a vmcsubastas.com.", 0.86, sibling=True),
        ], key=lambda f: f.score, reverse=True)
        discarded = [
            _frag("La Comisión", "¿Cuánto es la comisión?", 0.835,
                  url="https://ayuda.vmc.test/comision"),
            _frag(REG, CLAVE, 0.83),
        ]
        return RagResult(relevant=relevant, discarded=discarded, threshold=0.84)

    monkeypatch.setattr(ai_worker.rag, "retrieve", buscar)
    return consultas


def _conversacion(limpiar, anonymous=False):
    identity = None if anonymous else VmcIdentity(
        user_id="vmc_" + uuid.uuid4().hex[:8], name="Aaron"
    )
    conversation, _ = service.open_conversation(identity)
    limpiar(conversation.conversation_id)
    return conversation


def _escribe(conversation, texto, interaction=None):
    message, _ = service.post_user_message(
        conversation, client_message_id="cli-" + uuid.uuid4().hex, content=texto,
        metadata={"interaction": interaction} if interaction else None,
    )
    return message


def _atiende(message):
    ai_worker._process(
        AIJob(
            conversation_id=message.conversation_id, message_id=message.message_id,
            message_key=message.message_key, requested_at=message.created_at,
        ).model_dump_json()
    )


def _bot(conversation_id):
    return [
        m for m in repository.list_messages(conversation_id) if m.sender_type == SenderType.BOT
    ]


def _fresca(conversation):
    return repository.get_conversation(conversation.conversation_id)


def _usos(tablas, message_id):
    return [
        u for u in tablas["ai_usage"].scan()["Items"] if u.get("message_id") == message_id
    ]


# ───────────────────────── AC-W1: fuentes y hermanas en la respuesta ─────────────────────────


def test_la_respuesta_lleva_fuente_y_preguntas_hermanas(limpiar, modelo, indice):
    conversation = _conversacion(limpiar)

    _atiende(_escribe(conversation, "¿Cómo me registro en VMC?"))

    respuesta = _bot(conversation.conversation_id)[-1]
    assert respuesta.content == RESPUESTA
    assert respuesta.metadata["sources"] == [{"title": REG, "url": REG_URL}]
    interaction = respuesta.metadata["interaction"]
    assert interaction["type"] == related.RELATED_QUESTIONS
    assert [o["label"] for o in interaction["options"]] == [PJ, CLAVE], (
        "sin la respondida, sin la introduccion, sin el articulo de comision"
    )
    assert all(o["query"] == o["label"] for o in interaction["options"])
    assert respuesta.metadata["rag_query"] == "¿Cómo me registro en VMC?"


def test_sin_evidencia_no_hay_fuente_ni_botones_de_hermanas(limpiar, modelo, indice):
    conversation = _conversacion(limpiar)

    _atiende(_escribe(conversation, "¿cuánto está el dólar?"))

    meta = _bot(conversation.conversation_id)[-1].metadata or {}
    assert "sources" not in meta
    assert (meta.get("interaction") or {}).get("type") != related.RELATED_QUESTIONS


# ───────────────────────── AC-W2: el clic va al RAG sin clasificador ─────────────────────────


def test_el_clic_busca_esa_pregunta_sin_clasificar(limpiar, modelo, indice, tablas):
    conversation = _conversacion(limpiar)
    _atiende(_escribe(conversation, "¿Cómo me registro en VMC?"))
    antes = len(modelo.classify_calls())
    botones = _bot(conversation.conversation_id)[-1].metadata["interaction"]
    pj = next(o for o in botones["options"] if o["label"] == PJ)

    click = _escribe(_fresca(conversation), PJ, interaction={
        "action_id": botones["action_id"], "value": pj["value"],
    })
    _atiende(click)

    assert indice[-1] == PJ, "la consulta al indice es la pregunta canonica del boton"
    assert len(modelo.classify_calls()) == antes, "un clic no paga clasificador"
    assert len(modelo.answer_calls()) == 2
    assert _bot(conversation.conversation_id)[-1].content == RESPUESTA
    usos = _usos(tablas, click.message_id)
    assert [u["execution_type"] for u in usos] == ["RESPONSE"]
    assert usos[0]["source"] == "related:model"


# ───────────────────────── AC-W3: un clic que no corresponde se degrada ─────────────────────────


def test_un_clic_con_valor_inventado_se_trata_como_texto(limpiar, modelo, indice):
    conversation = _conversacion(limpiar)
    _atiende(_escribe(conversation, "¿Cómo me registro en VMC?"))

    _atiende(_escribe(_fresca(conversation), "¿Cómo me registro?", interaction={
        "action_id": related.RELATED_ACTION_ID, "value": "Q9",
    }))

    assert len(modelo.classify_calls()) == 2, "sin boton valido, el texto se clasifica"
    assert _bot(conversation.conversation_id)[-1].content == RESPUESTA


def test_un_clic_sobre_botones_viejos_se_trata_como_texto(limpiar, modelo, indice):
    """El usuario dejo los botones atras (escribio otra cosa y el bot contesto): el clic ya
    no corresponde al ultimo mensaje del bot."""
    conversation = _conversacion(limpiar)
    _atiende(_escribe(conversation, "¿Cómo me registro en VMC?"))
    viejos = _bot(conversation.conversation_id)[-1].metadata["interaction"]
    _atiende(_escribe(_fresca(conversation), "¿cuánto está el dólar?"))  # sin evidencia
    llamadas = len(modelo.classify_calls())

    _atiende(_escribe(_fresca(conversation), PJ, interaction={
        "action_id": viejos["action_id"], "value": viejos["options"][0]["value"],
    }))

    assert len(modelo.classify_calls()) == llamadas + 1
    assert indice[-1] == PJ, "el texto del boton se busca tal cual, como cualquier mensaje"


# ───────────────────────── AC-W4: estado de cuenta ─────────────────────────


def test_el_autenticado_llega_al_redactor_con_cuenta(limpiar, modelo, indice):
    conversation = _conversacion(limpiar)

    _atiende(_escribe(conversation, "¿Cómo me registro en VMC?"))

    system = modelo.answer_calls()[-1]["system"]
    assert prompts.WRITER_USER_AUTHENTICATED in system
    assert prompts.WRITER_USER_ANONYMOUS not in system


def test_el_anonimo_llega_al_redactor_sin_cuenta(limpiar, modelo, indice):
    conversation = _conversacion(limpiar, anonymous=True)

    _atiende(_escribe(conversation, "¿Cómo me registro en VMC?"))

    system = modelo.answer_calls()[-1]["system"]
    assert prompts.WRITER_USER_ANONYMOUS in system
    assert prompts.WRITER_USER_AUTHENTICATED not in system


# ───────────────────────── AC-W5: "ok" tras una respuesta completa cierra ─────────────────────────


def test_ok_tras_una_respuesta_completa_es_el_cierre_trivial(limpiar, modelo, indice):
    """Los botones de hermanas hacen que la respuesta NO sea una pregunta abierta: un "ok"
    despues es el acuse de cierre, no una continuacion que vuelva a pagar redactor."""
    conversation = _conversacion(limpiar)
    _atiende(_escribe(conversation, "¿Cómo me registro en VMC?"))

    _atiende(_escribe(_fresca(conversation), "ok"))

    assert _bot(conversation.conversation_id)[-1].content == prompts.TRIVIAL_THANKS_RESPONSE
    assert len(modelo.answer_calls()) == 1


# ───────────────────── AC-W6: la pregunta respondida no se repite como boton ─────────────────────


@pytest.mark.parametrize("indice", [{"como": 0.87, "pj": 0.9}], indirect=True)
def test_con_persona_juridica_primero_el_boton_no_repite_como_me_registro(
    limpiar, modelo, indice
):
    """Prueba real de Aaron (2026-09-03): "Hola como me registro" puso a persona juridica
    primero en el indice y los botones salieron "formulario", "contraseña" y "¿Como me
    registro?" — repitiendo la respondida y escondiendo persona juridica."""
    conversation = _conversacion(limpiar)

    _atiende(_escribe(conversation, "Hola como me registro"))

    labels = [o["label"] for o in
              _bot(conversation.conversation_id)[-1].metadata["interaction"]["options"]]
    assert COMO not in labels
    assert labels[0] == PJ


# ───────────────── AC-W7: boton de asesor cuando la respuesta manda a contactar ─────────────────


def test_si_la_respuesta_manda_a_contactar_sale_el_boton_y_abre_el_formulario_sin_ia(
    limpiar, modelo, indice, tablas
):
    modelo.answer = "Si nunca te registraste, pídeme un asesor aquí mismo para validar tus datos."
    conversation = _conversacion(limpiar)
    _atiende(_escribe(conversation, "¿Cómo me registro en VMC?"))
    botones = _bot(conversation.conversation_id)[-1].metadata["interaction"]
    asesor = botones["options"][-1]
    assert asesor["label"] == prompts.RELATED_ADVISOR_BUTTON
    assert asesor["kind"] == "handoff" and asesor["value"] == related.HANDOFF_VALUE
    llamadas = len(modelo.calls)

    click = _escribe(_fresca(conversation), asesor["label"], interaction={
        "action_id": botones["action_id"], "value": asesor["value"],
    })
    _atiende(click)

    respuesta = _bot(conversation.conversation_id)[-1]
    assert respuesta.content == prompts.HANDOFF_OFFER_RESPONSE
    assert respuesta.metadata["interaction"]["type"] == "HANDOFF_FORM"
    assert len(modelo.calls) == llamadas, "el boton de asesor no toca ningun modelo"
    usos = _usos(tablas, click.message_id)
    assert [u["source"] for u in usos] == ["handoff_offer:related_button"]


def test_sin_sugerencia_de_contacto_no_hay_boton_de_asesor(limpiar, modelo, indice):
    conversation = _conversacion(limpiar)

    _atiende(_escribe(conversation, "¿Cómo me registro en VMC?"))

    kinds = [o["kind"] for o in
             _bot(conversation.conversation_id)[-1].metadata["interaction"]["options"]]
    assert "handoff" not in kinds
