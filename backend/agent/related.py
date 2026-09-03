"""Fuentes, preguntas hermanas y boton de asesor de una respuesta con evidencia (D-030,
2026-09-03).

Tres cosas que antes hacia el modelo (mal y pagando) y ahora salen de la evidencia, sin
ninguna llamada:

- **Fuentes**: el enlace al Centro de Ayuda ya no se escribe dentro del texto (tres lineas de
  URL en una burbuja) sino que viaja en `metadata.sources` y el widget lo dibuja debajo de la
  respuesta ("Fuente: <titulo del articulo>"), como las citas de un asistente. Es
  determinista: sale del fragmento que se uso, asi que el modelo no puede inventar un enlace
  (RF-019 leido bien).
- **Preguntas hermanas**: el corpus esta escrito por preguntas (111 en 22 articulos) y cada
  fragmento es UNA pregunta con su respuesta completa. Tras responder una, las OTRAS
  preguntas del mismo articulo se ofrecen como botones ("¿Puedo registrarme como persona
  juridica?" debajo de "¿Como me registro?"). Un clic manda esa pregunta canonica al RAG
  directo — sin clasificador — igual que un paso de flujo (D-028). Reemplaza al "¿te explico
  el siguiente paso?" que el redactor prometia y que costaba una llamada de ~1.900 tokens de
  entrada por 30 de salida en cada "si" (medido 2026-09-03, conversacion real).
- **Boton de asesor**: cuando la respuesta (o su evidencia) manda a "contactarnos por el
  chat en linea", el boton "Contactar con un asesor" abre el formulario de D-029 sin pasar
  por ningun modelo. Pedido de Aaron (2026-09-03) al ver "contactanos mediante nuestro chat"
  como texto suelto en la respuesta de "el formulario me impide registrarme".

Modulo puro (regla de `backend/__init__.py`): definiciones y funciones sin I/O. Quien compone
esto con el repositorio y el widget es `workers/ai_worker.py`.

Diferencia con `agent/flows.py`: aqui NO hay estado en la conversacion. Las opciones viajan
en la metadata del mensaje del bot y el clic se valida contra ESE mensaje (el ultimo del bot):
si el usuario escribe otra cosa, los botones simplemente quedan atras. Un clic sobre botones
viejos se degrada a texto normal, nunca a un error.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from backend.agent import prompts
from backend.agent.heuristics import normalize
from backend.agent.rag import Fragment

# Tipo de interaccion que el widget sabe dibujar (metadata del mensaje del bot).
RELATED_QUESTIONS = "RELATED_QUESTIONS"
# `action_id` del evento del clic (el API lo exige en mayusculas, `InteractionIn`).
RELATED_ACTION_ID = "RELATED_QUESTION"
# `value` del boton de asesor; los de pregunta son Q1, Q2, Q3.
HANDOFF_VALUE = "ADVISOR"
# Cuantos botones de pregunta como maximo: mas de tres ya no es una sugerencia, es un menu.
MAX_RELATED = 3

KIND_QUESTION = "question"
KIND_HANDOFF = "handoff"

_TRAILING_DECORATION = frozenset({"So", "Sk", "Sm", "Mn", "Cf", "Zs", "Po"})

# Palabras que no distinguen una pregunta de otra dentro del mismo articulo. Cortas y
# deliberadamente pocas: solo las que aparecen en casi cualquier pregunta del corpus.
_STOPWORDS = frozenset(
    "a al como con de del el ella en es hay la las lo los me mi mis o para por que se si su "
    "sus un una y ya hola buenas dia dias tarde tardes".split()
)
_WORD = re.compile(r"[a-z0-9]+")

# Lo que en una respuesta (o en su evidencia) significa "habla con una persona del equipo".
# Sobre texto normalizado (sin tildes). "asesor" entra porque el propio prompt le pide al
# redactor ofrecerlo cuando el contexto no alcanza.
_ADVISOR_HINT = re.compile(
    r"\b(asesor(es|a|as)?|contact[a-z]*|chat en linea|escribenos|comunicate|comuniquese|"
    r"soporte|atencion al cliente)\b"
)


@dataclass(frozen=True, slots=True)
class Click:
    """Un clic valido sobre los botones de la ultima respuesta del bot."""

    kind: str  # KIND_QUESTION | KIND_HANDOFF
    query: str | None = None  # la pregunta canonica (solo KIND_QUESTION)


def question_of(fragment: Fragment) -> str | None:
    """La pregunta que responde el fragmento, o None si es la introduccion del articulo.

    Los chunks de la ingesta (`scripts/helpcenter_fetch.py`) tienen tres partes separadas por
    salto de linea: titulo del articulo, pregunta, respuesta. Los 22 fragmentos de
    introduccion no tienen pregunta: su segunda linea es prosa ("Para registrarte, ingresa
    a...") y no debe salir como boton. Verificado sobre los 133 chunks del 2026-09-03: 111
    con pregunta, 22 sin ella, ninguno ambiguo.
    """
    lines = [line.strip() for line in (fragment.text or "").split("\n")]
    if len(lines) < 2 or not lines[1]:
        return None
    candidate = lines[1]
    core = candidate
    while core and unicodedata.category(core[-1]) in _TRAILING_DECORATION and core[-1] != "?":
        core = core[:-1].rstrip()
    if candidate.startswith("¿") or core.endswith("?"):
        return candidate
    return None


def sources(evidence: list[Fragment]) -> list[dict[str, str]]:
    """Las fuentes de la evidencia, sin repetir, en el orden en que llegaron al redactor.

    Con la expansion por tema (rag.py) la evidencia suele ser un solo articulo, asi que casi
    siempre es una. `title` es lo que se lee; `url` a donde va.
    """
    seen: set[str] = set()
    result: list[dict[str, str]] = []
    for fragment in evidence:
        url = (fragment.source_url or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        result.append({"title": fragment.topic or url, "url": url})
    return result


def _stems(text: str) -> set[str]:
    """Raices toscas (6 letras) de las palabras con contenido: "registro", "registrarme" y
    "registrarse" caen en la misma. Suficiente para comparar dos preguntas del mismo
    articulo; no es un stemmer y no pretende serlo."""
    return {
        word[:6]
        for word in _WORD.findall(normalize(text))
        if word not in _STOPWORDS and len(word) > 2
    }


def _similarity(query: str, question: str | None) -> float:
    """Jaccard entre las raices de la consulta y las de la pregunta del fragmento. Jaccard y
    no solapamiento simple: penaliza la pregunta larga que comparte una palabra ("registr")
    con la corta que es casi identica a la consulta."""
    if not question:
        return 0.0
    a, b = _stems(query), _stems(question)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def answered_fragment(query: str, evidence: list[Fragment]) -> Fragment | None:
    """El fragmento que RESPONDE la consulta: el de pregunta mas parecida a lo que se busco
    y, a igual parecido (o sin ninguno), el de mejor score.

    No vale "el de mejor score" a secas: con "Hola como me registro" el indice puso primero
    el fragmento de persona juridica (2026-09-03, prueba real de Aaron), y con esa regla el
    boton repetia "¿Como me registro?" y escondia justo el de persona juridica.
    """
    if not evidence:
        return None
    return max(
        evidence,
        key=lambda f: (round(_similarity(query, question_of(f)), 3), f.score),
    )


def related_questions(
    query: str, evidence: list[Fragment], candidates: list[Fragment]
) -> list[str]:
    """Las otras preguntas del articulo que respondio, para ofrecer como botones.

    - El articulo es el del fragmento que respondio (`answered_fragment`).
    - Ese fragmento se excluye: es lo que se acaba de contestar. Los demas del mismo articulo
      entran por score, esten o no dentro de la evidencia (con la expansion por tema el
      redactor pudo verlos, pero el prompt le pide responder LA pregunta, no el articulo).
    - Solo fragmentos con pregunta (`question_of`): la introduccion no es un boton.
    - Nada de otros articulos: los botones son "mas sobre esto", no un menu del corpus.
    - `candidates` son todos los hits que trajo el indice (`RagResult.all_fragments`): el
      articulo de registro tiene 5 preguntas y el indice devuelve 8 candidatos, asi que en
      general estan todas; si alguna no vino, simplemente no se ofrece.
    """
    answered = answered_fragment(query, evidence)
    if answered is None or not answered.topic:
        return []
    seen: set[str] = set()
    answered_question = question_of(answered)
    if answered_question:
        seen.add(answered_question)
    pool = sorted(
        (f for f in candidates if f.topic == answered.topic and f != answered),
        key=lambda f: f.score, reverse=True,
    )
    result: list[str] = []
    for fragment in pool:
        question = question_of(fragment)
        if not question or question in seen:
            continue
        seen.add(question)
        result.append(question)
        if len(result) >= MAX_RELATED:
            break
    return result


def suggests_advisor(answer: str, evidence_texts: list[str]) -> bool:
    """La respuesta o su evidencia mandan a hablar con una persona del equipo. Se mira
    tambien la evidencia porque el redactor puede resumir el "contactanos por el chat" con
    otras palabras y el usuario se quedaria sin el boton."""
    corpus = " ".join([answer or "", *evidence_texts])
    return bool(_ADVISOR_HINT.search(normalize(corpus)))


def related_metadata(questions: list[str], *, advisor: bool = False) -> dict | None:
    """La metadata del mensaje del bot que el widget dibuja como botones (MAPEO.md §3.1).

    Cada opcion de pregunta lleva su `query`: es lo que va al RAG al hacer clic, y el servidor
    lo lee de AQUI (del mensaje persistido), no del payload del clic — editar el HTML no
    inventa consultas. El boton de asesor (`kind = handoff`) no lleva consulta: abre el
    formulario de D-029. Sin `flow_version`: no hay estado que versionar.
    """
    options = [
        {"label": question, "value": f"Q{index}", "query": question, "kind": KIND_QUESTION}
        for index, question in enumerate(questions, start=1)
    ]
    if advisor:
        options.append({
            "label": prompts.RELATED_ADVISOR_BUTTON, "value": HANDOFF_VALUE,
            "kind": KIND_HANDOFF,
        })
    if not options:
        return None
    return {
        "interaction": {
            "type": RELATED_QUESTIONS,
            "action_id": RELATED_ACTION_ID,
            "options": options,
        }
    }


def resolve_click(interaction: dict | None, last_bot_metadata: dict | None) -> Click | None:
    """El clic, si corresponde a los botones que el bot dejo en su ULTIMO mensaje; None en
    cualquier otro caso (botones viejos, valor inventado, payload malformado). Un clic
    invalido no es un error: el mensaje sigue el pipeline como texto normal.
    """
    if not isinstance(interaction, dict) or interaction.get("action_id") != RELATED_ACTION_ID:
        return None
    offered = (last_bot_metadata or {}).get("interaction")
    if not isinstance(offered, dict) or offered.get("type") != RELATED_QUESTIONS:
        return None
    value = interaction.get("value")
    for option in offered.get("options") or []:
        if not isinstance(option, dict) or option.get("value") != value:
            continue
        if option.get("kind") == KIND_HANDOFF or value == HANDOFF_VALUE:
            return Click(kind=KIND_HANDOFF)
        query = option.get("query")
        return Click(kind=KIND_QUESTION, query=str(query)) if query else None
    return None
