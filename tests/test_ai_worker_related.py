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


import pytest

from backend.agent import prompts, related
from backend.agent.rag import Fragment, RagResult
from backend.core.config import get_settings
from backend.workers import ai_worker
from tests.helpers.fakes import FakeLLM, install_llm
from tests.helpers.scenario import (
    atiende,
    conversacion,
    escribe,
    fresca,
    respuestas_bot,
    usos_del_mensaje,
)

pytestmark = pytest.mark.usefixtures("entorno_dynamo", "sin_rate_limit")

REG = "¡Registrarte es fácil y rápido!"
REG_URL = "https://ayuda.vmc.test/registro"
COMO = "¿Cómo me registro?"
PJ = "¿Puedo registrarme como persona jurídica?"
CLAVE = "He olvidado mi contraseña, ¿cómo puedo recuperar el ingreso a mi cuenta?"
FORM_Q = "Estoy intentando registrarme, pero el formulario me impide realizarlo, ¿qué puedo hacer?"
RESPUESTA = "Para registrarte entra a vmcsubastas.com y dale a Regístrate 🙂"
# D-031: el mensaje sugerido que cierra toda lista de hermanas.
ASESOR = related.ADVISOR_OPTION_LABEL


def _frag(topic, question, score, url=REG_URL, sibling=False):
    return Fragment(text=f"{topic}\n{question}\nrespuesta.", topic=topic, source_url=url,
                    score=score, sibling=sibling)


@pytest.fixture
def modelo(monkeypatch):
    return install_llm(monkeypatch, FakeLLM(answer=RESPUESTA))


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


# ───────────────────────── AC-W1: fuentes y hermanas en la respuesta ─────────────────────────


def test_la_respuesta_lleva_fuente_y_preguntas_hermanas(limpiar, modelo, indice):
    conversation = conversacion(limpiar)

    atiende(escribe(conversation, "¿Cómo me registro en VMC?"))

    respuesta = respuestas_bot(conversation.conversation_id)[-1]
    assert respuesta.content == RESPUESTA
    assert respuesta.metadata["sources"] == [{"title": REG, "url": REG_URL}]
    interaction = respuesta.metadata["interaction"]
    assert interaction["type"] == related.RELATED_QUESTIONS
    assert [o["label"] for o in interaction["options"]] == [PJ, CLAVE, ASESOR], (
        "sin la respondida, sin la introduccion, sin el articulo de comision; el asesor al final"
    )
    assert all(o["query"] == o["label"] for o in interaction["options"][:-1])
    assert respuesta.metadata["rag_query"] == "¿Cómo me registro en VMC?"


# ───────────── D-031: el ultimo mensaje sugerido es el asesor y su clic va por reglas ─────────────


def _clic_de_asesor(conversation):
    botones = respuestas_bot(conversation.conversation_id)[-1].metadata["interaction"]
    asesor = botones["options"][-1]
    assert asesor == {"label": ASESOR, "value": related.ADVISOR_OPTION_VALUE, "kind": "handoff"}
    return escribe(fresca(conversation), asesor["label"], interaction={
        "action_id": botones["action_id"], "value": asesor["value"],
    })


def test_el_clic_en_el_boton_de_asesor_ofrece_el_formulario_sin_modelo(
    limpiar, modelo, indice, tablas
):
    conversation = conversacion(limpiar)
    atiende(escribe(conversation, "¿Cómo me registro en VMC?"))
    antes = len(modelo.classify_calls())

    click = _clic_de_asesor(conversation)
    atiende(click)

    ultima = respuestas_bot(conversation.conversation_id)[-1]
    assert ultima.content == prompts.HANDOFF_OFFER_RESPONSE
    assert ultima.metadata["interaction"]["type"] == "HANDOFF_FORM"
    assert len(modelo.classify_calls()) == antes, "se reconoce por estructura, sin modelo"
    usos = usos_del_mensaje(tablas, conversation.conversation_id, click.message_id)
    assert [u["source"] for u in usos] == [
        "handoff_offer:advisor_button"
    ], "una sola fila, gratis, sin clasificacion"


def test_el_visitante_que_pulsa_el_boton_de_asesor_recibe_el_login(
    limpiar, modelo, indice, tablas
):
    conversation = conversacion(limpiar, autenticada=False)
    atiende(escribe(conversation, "¿Cómo me registro en VMC?"))
    antes = len(modelo.classify_calls())

    click = _clic_de_asesor(conversation)
    atiende(click)

    ultima = respuestas_bot(conversation.conversation_id)[-1]
    assert ultima.content == prompts.ANON_LOGIN_RESPONSE
    assert ultima.metadata["interaction"] == {
        "type": "LINKS",
        "options": [{"label": prompts.LOGIN_LINK_LABEL, "url": get_settings().vmc_login_url}],
    }
    assert len(modelo.classify_calls()) == antes, "el anonimo tampoco toca ningun modelo"
    usos = usos_del_mensaje(tablas, conversation.conversation_id, click.message_id)
    assert [u["source"] for u in usos] == ["login:advisor_button"]


def test_un_clic_de_asesor_sobre_botones_viejos_sigue_como_texto(limpiar, modelo, indice):
    """El usuario dejo los botones atras: el clic ya no corresponde al ultimo mensaje del
    bot, asi que "Contactar asesor" se atiende como texto (orquestador), nunca como error."""
    conversation = conversacion(limpiar)
    atiende(escribe(conversation, "¿Cómo me registro en VMC?"))
    viejos = respuestas_bot(conversation.conversation_id)[-1].metadata["interaction"]
    atiende(escribe(fresca(conversation), "¿cuánto está el dólar?"))  # sin evidencia
    llamadas = len(modelo.classify_calls())

    atiende(escribe(fresca(conversation), related.ADVISOR_OPTION_LABEL, interaction={
        "action_id": viejos["action_id"], "value": related.ADVISOR_OPTION_VALUE,
    }))

    assert len(modelo.classify_calls()) == llamadas + 1, "sin boton vigente, el texto se clasifica"


def test_sin_evidencia_no_hay_fuente_ni_botones_de_hermanas(limpiar, modelo, indice):
    conversation = conversacion(limpiar)

    atiende(escribe(conversation, "¿cuánto está el dólar?"))

    meta = respuestas_bot(conversation.conversation_id)[-1].metadata or {}
    assert "sources" not in meta
    assert (meta.get("interaction") or {}).get("type") != related.RELATED_QUESTIONS


# ───────────────────────── AC-W2: el clic va al RAG sin clasificador ─────────────────────────


def test_el_clic_busca_esa_pregunta_sin_clasificar(limpiar, modelo, indice, tablas):
    conversation = conversacion(limpiar)
    atiende(escribe(conversation, "¿Cómo me registro en VMC?"))
    antes = len(modelo.classify_calls())
    botones = respuestas_bot(conversation.conversation_id)[-1].metadata["interaction"]
    pj = next(o for o in botones["options"] if o["label"] == PJ)

    click = escribe(fresca(conversation), PJ, interaction={
        "action_id": botones["action_id"], "value": pj["value"],
    })
    atiende(click)

    assert indice[-1] == PJ, "la consulta al indice es la pregunta canonica del boton"
    assert len(modelo.classify_calls()) == antes, "un clic no paga clasificador"
    assert len(modelo.answer_calls()) == 2
    assert respuestas_bot(conversation.conversation_id)[-1].content == RESPUESTA
    usos = usos_del_mensaje(tablas, conversation.conversation_id, click.message_id)
    assert [u["execution_type"] for u in usos] == ["RESPONSE"]
    assert usos[0]["source"] == "related:model"


# ───────────────────────── AC-W3: un clic que no corresponde se degrada ─────────────────────────


def test_un_clic_con_valor_inventado_se_trata_como_texto(limpiar, modelo, indice):
    conversation = conversacion(limpiar)
    atiende(escribe(conversation, "¿Cómo me registro en VMC?"))

    atiende(escribe(fresca(conversation), "¿Cómo me registro?", interaction={
        "action_id": related.RELATED_ACTION_ID, "value": "Q9",
    }))

    assert len(modelo.classify_calls()) == 2, "sin boton valido, el texto se clasifica"
    assert respuestas_bot(conversation.conversation_id)[-1].content == RESPUESTA


def test_un_clic_sobre_botones_viejos_se_trata_como_texto(limpiar, modelo, indice):
    """El usuario dejo los botones atras (escribio otra cosa y el bot contesto): el clic ya
    no corresponde al ultimo mensaje del bot."""
    conversation = conversacion(limpiar)
    atiende(escribe(conversation, "¿Cómo me registro en VMC?"))
    viejos = respuestas_bot(conversation.conversation_id)[-1].metadata["interaction"]
    atiende(escribe(fresca(conversation), "¿cuánto está el dólar?"))  # sin evidencia
    llamadas = len(modelo.classify_calls())

    atiende(escribe(fresca(conversation), PJ, interaction={
        "action_id": viejos["action_id"], "value": viejos["options"][0]["value"],
    }))

    assert len(modelo.classify_calls()) == llamadas + 1
    assert indice[-1] == PJ, "el texto del boton se busca tal cual, como cualquier mensaje"


# ───────────────────────── AC-W4: estado de cuenta ─────────────────────────


def test_el_autenticado_llega_al_redactor_con_cuenta(limpiar, modelo, indice):
    conversation = conversacion(limpiar)

    atiende(escribe(conversation, "¿Cómo me registro en VMC?"))

    system = modelo.answer_calls()[-1]["system"]
    assert prompts.WRITER_USER_AUTHENTICATED in system
    assert prompts.WRITER_USER_ANONYMOUS not in system


def test_el_anonimo_llega_al_redactor_sin_cuenta(limpiar, modelo, indice):
    conversation = conversacion(limpiar, autenticada=False)

    atiende(escribe(conversation, "¿Cómo me registro en VMC?"))

    system = modelo.answer_calls()[-1]["system"]
    assert prompts.WRITER_USER_ANONYMOUS in system
    assert prompts.WRITER_USER_AUTHENTICATED not in system


# ───────────────────────── AC-W5: "ok" tras una respuesta completa cierra ─────────────────────────


def test_ok_tras_una_respuesta_completa_es_el_cierre_trivial(limpiar, modelo, indice):
    """Los botones de hermanas hacen que la respuesta NO sea una pregunta abierta: un "ok"
    despues es el acuse de cierre, no una continuacion que vuelva a pagar redactor."""
    conversation = conversacion(limpiar)
    atiende(escribe(conversation, "¿Cómo me registro en VMC?"))

    atiende(escribe(fresca(conversation), "ok"))

    ultima = respuestas_bot(conversation.conversation_id)[-1]
    assert ultima.content == prompts.TRIVIAL_THANKS_RESPONSE
    assert len(modelo.answer_calls()) == 1


# ───────────────────── AC-W6: la pregunta respondida no se repite como boton ─────────────────────


@pytest.mark.parametrize("indice", [{"como": 0.87, "pj": 0.9}], indirect=True)
def test_con_persona_juridica_primero_el_boton_no_repite_como_me_registro(
    limpiar, modelo, indice
):
    """Prueba real de Aaron (2026-09-03): "Hola como me registro" puso a persona juridica
    primero en el indice y los botones salieron "formulario", "contraseña" y "¿Como me
    registro?" — repitiendo la respondida y escondiendo persona juridica."""
    conversation = conversacion(limpiar)

    atiende(escribe(conversation, "Hola como me registro"))

    labels = [o["label"] for o in
              respuestas_bot(conversation.conversation_id)[-1].metadata["interaction"]["options"]]
    assert COMO not in labels
    assert labels[0] == PJ


# ───────────── AC-W7: una hermana fuera de top_k (overflow del RAG) tambien se ofrece ─────────────


def test_una_pregunta_del_articulo_mas_alla_de_top_k_sale_como_boton(
    limpiar, modelo, monkeypatch
):
    """Segunda prueba real de Aaron (2026-09-03): los 4 primeros hits eran del articulo de
    registro (intro, formulario, contraseña, "¿Como me registro?") y persona juridica era el
    quinto. El RAG lo tiraba con el resto del lookahead y el boton no salia."""
    intro = _frag(REG, "Para registrarte, ingresa a vmcsubastas.com.", 0.8586)
    relevant = [intro, _frag(REG, FORM_Q, 0.8581), _frag(REG, CLAVE, 0.8531),
                _frag(REG, COMO, 0.8525)]
    monkeypatch.setattr(
        ai_worker.rag, "retrieve",
        lambda text, **kwargs: RagResult(
            relevant=relevant, discarded=[], threshold=0.84,
            overflow=[_frag(REG, PJ, 0.8490)],
        ),
    )
    conversation = conversacion(limpiar)

    atiende(escribe(conversation, "Hola como me registro"))

    labels = [o["label"] for o in
              respuestas_bot(conversation.conversation_id)[-1].metadata["interaction"]["options"]]
    # Por score del indice (el orden real de esa prueba): persona juridica entra tercera.
    assert labels == [FORM_Q, CLAVE, PJ, ASESOR]
