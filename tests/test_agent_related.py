"""Fuentes y preguntas hermanas (D-030, `agent/related.py`). Puro: sin Pinecone ni modelo.

Criterios:
  AC-RL1  la pregunta de un fragmento es su segunda linea SOLO si es una pregunta; la
          introduccion del articulo (prosa) no tiene pregunta
  AC-RL2  las fuentes salen deduplicadas por URL y en el orden de la evidencia
  AC-RL3  las hermanas son las OTRAS preguntas del articulo del mejor fragmento, por score,
          sin la que se acaba de responder, sin la introduccion, sin otros articulos y
          como maximo MAX_RELATED
  AC-RL4  la metadata lleva la consulta de cada boton; un clic se resuelve contra ESA
          metadata y cualquier otra cosa (accion ajena, valor inventado, botones de otro
          tipo) da None
"""

from backend.agent import related
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


# ───────────────────────── AC-RL3: hermanas ─────────────────────────


def test_las_hermanas_son_las_otras_preguntas_del_articulo_por_score():
    evidence = [COMO, PJ, INTRO]
    candidates = evidence + [CLAVE, FORM, COMISION]

    assert related.related_questions(evidence, candidates) == [
        "¿Puedo registrarme como persona jurídica?",
        "He olvidado mi contraseña, ¿cómo puedo recuperar el ingreso a mi cuenta?",
        "Estoy intentando registrarme, pero el formulario me impide realizarlo, "
        "¿qué puedo hacer?",
    ]


def test_el_tope_es_max_related():
    extra = _frag(REG, "¿Puedo cambiar mi correo?", score=0.80)
    evidence = [COMO]
    candidates = [COMO, PJ, CLAVE, FORM, extra]

    hermanas = related.related_questions(evidence, candidates)

    assert len(hermanas) == related.MAX_RELATED == 3
    assert "¿Puedo cambiar mi correo?" not in hermanas, "la de menor score queda fuera"


def test_otro_articulo_no_entra_aunque_este_entre_los_candidatos():
    hermanas = related.related_questions([COMO], [COMO, COMISION])
    assert hermanas == []


def test_la_introduccion_como_mejor_fragmento_no_bloquea_a_las_hermanas():
    """Si el hit mas alto es la introduccion, las preguntas del articulo se ofrecen todas."""
    intro_alto = _frag(REG, "Para registrarte, ingresa a vmcsubastas.com.", score=0.9)
    hermanas = related.related_questions([intro_alto, COMO], [intro_alto, COMO, PJ])
    assert hermanas == ["¿Cómo me registro?", "¿Puedo registrarme como persona jurídica?"]


def test_sin_evidencia_no_hay_hermanas():
    assert related.related_questions([], [COMO]) == []


# ───────────────────────── AC-RL4: metadata y clic ─────────────────────────


def test_la_metadata_lleva_la_consulta_de_cada_boton():
    meta = related.related_metadata(["¿A?", "¿B?"])
    assert meta == {
        "interaction": {
            "type": related.RELATED_QUESTIONS,
            "action_id": related.RELATED_ACTION_ID,
            "options": [
                {"label": "¿A?", "value": "Q1", "query": "¿A?"},
                {"label": "¿B?", "value": "Q2", "query": "¿B?"},
            ],
        }
    }
    assert related.related_metadata([]) is None


def test_el_clic_se_resuelve_contra_la_metadata_del_bot():
    meta = related.related_metadata(["¿A?", "¿B?"])
    click = {"action_id": related.RELATED_ACTION_ID, "value": "Q2"}
    assert related.resolve_click(click, meta) == "¿B?"


def test_un_clic_que_no_corresponde_da_none():
    meta = related.related_metadata(["¿A?"])
    assert related.resolve_click({"action_id": related.RELATED_ACTION_ID, "value": "Q9"},
                                 meta) is None
    assert related.resolve_click({"action_id": "SELECT_OFFER_TYPE", "value": "Q1"},
                                 meta) is None
    assert related.resolve_click({"action_id": related.RELATED_ACTION_ID, "value": "Q1"},
                                 None) is None
    assert related.resolve_click({"action_id": related.RELATED_ACTION_ID, "value": "Q1"},
                                 {"interaction": {"type": "QUICK_REPLIES", "options": [
                                     {"value": "Q1", "query": "hack"}]}}) is None
    assert related.resolve_click(None, meta) is None
    assert related.resolve_click("Q1", meta) is None
