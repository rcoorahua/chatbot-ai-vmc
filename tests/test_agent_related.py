"""Fuentes, preguntas hermanas y boton de asesor (D-030, `agent/related.py`). Puro: sin
Pinecone ni modelo.

Criterios:
  AC-RL1  la pregunta de un fragmento es su segunda linea SOLO si es una pregunta; la
          introduccion del articulo (prosa) no tiene pregunta
  AC-RL2  las fuentes salen deduplicadas por URL y en el orden de la evidencia
  AC-RL3  la pregunta RESPONDIDA es la mas parecida a lo que se busco (no la de mejor
          score): con "Hola como me registro" y persona juridica primero en el indice, el
          boton no puede repetir "¿Como me registro?" ni esconder persona juridica
          (prueba real de Aaron, 2026-09-03)
  AC-RL4  las hermanas son las OTRAS preguntas del articulo, por score, sin la respondida,
          sin la introduccion, sin otros articulos y como maximo MAX_RELATED
  AC-RL5  si la respuesta o su evidencia mandan a contactar al equipo, sale el boton de
          asesor (kind = handoff), sin consulta
  AC-RL6  la metadata lleva la consulta de cada boton; un clic se resuelve contra ESA
          metadata y cualquier otra cosa (accion ajena, valor inventado, botones de otro
          tipo) da None
"""

from backend.agent import prompts, related
from backend.agent.rag import Fragment

REG = "¡Registrarte es fácil y rápido!"
REG_URL = "https://ayuda.vmc.test/registro"
COM = "La Comisión, ¿Por qué, cuánto y cómo se paga?"


def _frag(topic, question, answer="respuesta", score=0.85, url=REG_URL):
    return Fragment(text=f"{topic}\n{question}\n{answer}", topic=topic, source_url=url,
                    score=score)


INTRO = _frag(REG, "Para registrarte, ingresa a vmcsubastas.com y haz clic en Ingresar.",
              score=0.86)
COMO = _frag(REG, "¿Cómo me registro?", score=0.875)
PJ = _frag(REG, "¿Puedo registrarme como persona jurídica?", score=0.87)
CLAVE = _frag(REG, "He olvidado mi contraseña, ¿cómo puedo recuperar el ingreso a mi cuenta?",
              score=0.83)
FORM = _frag(REG, "Estoy intentando registrarme, pero el formulario me impide realizarlo, "
             "¿qué puedo hacer?", score=0.82)
COMISION = _frag(COM, "¿Cuánto es la comisión?", score=0.84, url="https://ayuda.vmc.test/com")


# ───────────────────────── AC-RL1: la pregunta del fragmento ─────────────────────────


def test_la_segunda_linea_es_la_pregunta():
    assert related.question_of(COMO) == "¿Cómo me registro?"
    assert related.question_of(CLAVE).startswith("He olvidado")


def test_la_introduccion_no_tiene_pregunta():
    assert related.question_of(INTRO) is None


def test_un_emoji_al_final_no_esconde_la_pregunta():
    assert related.question_of(_frag(REG, "¿Y luego qué hago? 🚗")) == "¿Y luego qué hago? 🚗"


def test_un_fragmento_de_una_sola_linea_no_tiene_pregunta():
    assert related.question_of(Fragment(text="solo texto", topic=REG)) is None


# ───────────────────────── AC-RL2: fuentes ─────────────────────────


def test_las_fuentes_se_deduplican_por_url_en_orden():
    assert related.sources([COMO, PJ, COMISION, INTRO]) == [
        {"title": REG, "url": REG_URL},
        {"title": COM, "url": "https://ayuda.vmc.test/com"},
    ]


def test_sin_url_no_hay_fuente():
    assert related.sources([Fragment(text="x", topic=REG)]) == []


# ───────────────────────── AC-RL3: la pregunta respondida ─────────────────────────


def test_la_respondida_es_la_mas_parecida_a_la_consulta_no_la_de_mejor_score():
    pj_primero = _frag(REG, "¿Puedo registrarme como persona jurídica?", score=0.9)
    evidence = [pj_primero, COMO, INTRO]

    assert related.answered_fragment("Hola como me registro", evidence) == COMO
    assert related.answered_fragment("puedo registrarme como persona juridica?", evidence) \
        == pj_primero


def test_sin_parecido_con_ninguna_pregunta_manda_el_score():
    evidence = [COMO, PJ]
    assert related.answered_fragment("hola buenas", evidence) == COMO


def test_la_raiz_tosca_junta_registro_y_registrarme():
    assert related.answered_fragment("quiero registrarme", [PJ, COMO]) == COMO, (
        "Jaccard: la pregunta corta casi identica gana a la larga que solo comparte la raiz"
    )


# ───────────────────────── AC-RL4: hermanas ─────────────────────────


def test_las_hermanas_son_las_otras_preguntas_del_articulo_por_score():
    evidence = [COMO, PJ, INTRO]
    candidates = evidence + [CLAVE, FORM, COMISION]

    assert related.related_questions("¿Cómo me registro?", evidence, candidates) == [
        "¿Puedo registrarme como persona jurídica?",
        "He olvidado mi contraseña, ¿cómo puedo recuperar el ingreso a mi cuenta?",
        "Estoy intentando registrarme, pero el formulario me impide realizarlo, "
        "¿qué puedo hacer?",
    ]


def test_el_caso_real_hola_como_me_registro_con_persona_juridica_primero():
    """Lo que Aaron vio el 2026-09-03: botones "formulario", "contraseña" y "¿Como me
    registro?" (la respondida) y sin persona juridica."""
    pj_primero = _frag(REG, "¿Puedo registrarme como persona jurídica?", score=0.9)
    evidence = [pj_primero, COMO, INTRO]
    candidates = evidence + [CLAVE, FORM]

    hermanas = related.related_questions("Hola como me registro", evidence, candidates)

    assert "¿Cómo me registro?" not in hermanas
    assert hermanas[0] == "¿Puedo registrarme como persona jurídica?"
    assert len(hermanas) == 3


def test_el_tope_es_max_related():
    extra = _frag(REG, "¿Puedo cambiar mi correo?", score=0.80)
    hermanas = related.related_questions("como me registro", [COMO],
                                         [COMO, PJ, CLAVE, FORM, extra])

    assert len(hermanas) == related.MAX_RELATED == 3
    assert "¿Puedo cambiar mi correo?" not in hermanas, "la de menor score queda fuera"


def test_otro_articulo_no_entra_aunque_este_entre_los_candidatos():
    assert related.related_questions("como me registro", [COMO], [COMO, COMISION]) == []


def test_la_introduccion_como_mejor_fragmento_no_bloquea_a_las_hermanas():
    intro_alto = _frag(REG, "Para registrarte, ingresa a vmcsubastas.com.", score=0.9)
    hermanas = related.related_questions("hola buenas", [intro_alto, COMO],
                                         [intro_alto, COMO, PJ])
    assert hermanas == ["¿Cómo me registro?", "¿Puedo registrarme como persona jurídica?"]


def test_sin_evidencia_no_hay_hermanas():
    assert related.related_questions("x", [], [COMO]) == []


# ───────────────────────── AC-RL5: boton de asesor ─────────────────────────


def test_la_respuesta_que_manda_a_contactar_sugiere_asesor():
    assert related.suggests_advisor("Si nunca te registraste, contáctanos por el chat.", [])
    assert related.suggests_advisor("Pídeme un asesor aquí mismo 🙂", [])
    assert related.suggests_advisor("Ok.", ["Comunícate con nosotros mediante el chat en línea"])
    assert not related.suggests_advisor("Para registrarte entra a vmcsubastas.com.",
                                        ["Paso 1: ingresa. Paso 2: regístrate."])


def test_la_metadata_lleva_el_boton_de_asesor_al_final():
    meta = related.related_metadata(["¿A?"], advisor=True)
    options = meta["interaction"]["options"]
    assert options[0] == {"label": "¿A?", "value": "Q1", "query": "¿A?", "kind": "question"}
    assert options[1] == {
        "label": prompts.RELATED_ADVISOR_BUTTON, "value": related.HANDOFF_VALUE,
        "kind": "handoff",
    }
    assert related.related_metadata([], advisor=True)["interaction"]["options"] == [options[1]]


# ───────────────────────── AC-RL6: metadata y clic ─────────────────────────


def test_la_metadata_lleva_la_consulta_de_cada_boton():
    meta = related.related_metadata(["¿A?", "¿B?"])
    assert meta["interaction"]["type"] == related.RELATED_QUESTIONS
    assert meta["interaction"]["action_id"] == related.RELATED_ACTION_ID
    assert [o["query"] for o in meta["interaction"]["options"]] == ["¿A?", "¿B?"]
    assert "flow_version" not in meta["interaction"]
    assert related.related_metadata([]) is None


def test_el_clic_se_resuelve_contra_la_metadata_del_bot():
    meta = related.related_metadata(["¿A?", "¿B?"], advisor=True)
    assert related.resolve_click({"action_id": related.RELATED_ACTION_ID, "value": "Q2"},
                                 meta) == related.Click(kind=related.KIND_QUESTION, query="¿B?")
    assert related.resolve_click({"action_id": related.RELATED_ACTION_ID,
                                  "value": related.HANDOFF_VALUE},
                                 meta) == related.Click(kind=related.KIND_HANDOFF)


def test_un_clic_que_no_corresponde_da_none():
    meta = related.related_metadata(["¿A?"])
    click = {"action_id": related.RELATED_ACTION_ID, "value": "Q1"}
    assert related.resolve_click({"action_id": related.RELATED_ACTION_ID, "value": "Q9"},
                                 meta) is None
    assert related.resolve_click({"action_id": related.RELATED_ACTION_ID,
                                  "value": related.HANDOFF_VALUE},
                                 meta) is None, "el boton de asesor no se ofrecio"
    assert related.resolve_click({"action_id": "SELECT_OFFER_TYPE", "value": "Q1"},
                                 meta) is None
    assert related.resolve_click(click, None) is None
    assert related.resolve_click(click, {"interaction": {"type": "QUICK_REPLIES", "options": [
        {"value": "Q1", "query": "hack"}]}}) is None
    assert related.resolve_click(None, meta) is None
    assert related.resolve_click("Q1", meta) is None
