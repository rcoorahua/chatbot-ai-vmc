"""Fuentes y preguntas hermanas de una respuesta con evidencia (D-030, 2026-09-03).

Dos cosas que antes hacia el modelo (mal y pagando) y ahora salen de la evidencia, sin
ninguna llamada:

- **Fuentes**: el enlace al Centro de Ayuda ya no se escribe dentro del texto (tres lineas de
  URL en una burbuja) sino que viaja en `metadata.sources` y el widget lo dibuja como un chip
  debajo de la respuesta, como las citas de un asistente. Es determinista: sale del
  fragmento que se uso, asi que el modelo no puede inventar un enlace (RF-019 leido bien).
- **Preguntas hermanas**: el corpus esta escrito por preguntas (111 en 22 articulos) y cada
  fragmento es UNA pregunta con su respuesta completa. Tras responder una, las OTRAS
  preguntas del mismo articulo se ofrecen como botones ("¿Puedo registrarme como persona
  juridica?" debajo de "¿Como me registro?"). Un clic manda esa pregunta canonica al RAG
  directo — sin clasificador — igual que un paso de flujo (D-028). Reemplaza al "¿te explico
  el siguiente paso?" que el redactor prometia y que costaba una llamada de ~1.900 tokens de
  entrada por 30 de salida en cada "si" (medido 2026-09-03, conversacion real).

Modulo puro (regla de `backend/__init__.py`): definiciones y funciones sin I/O. Quien compone
esto con el repositorio y el widget es `workers/ai_worker.py`.

Diferencia con `agent/flows.py`: aqui NO hay estado en la conversacion. Las opciones viajan
en la metadata del mensaje del bot y el clic se valida contra ESE mensaje (el ultimo del bot):
si el usuario escribe otra cosa, los botones simplemente quedan atras. Un clic sobre botones
viejos se degrada a texto normal, nunca a un error.
"""

from __future__ import annotations

import unicodedata

from backend.agent.rag import Fragment

# Tipo de interaccion que el widget sabe dibujar (metadata del mensaje del bot).
RELATED_QUESTIONS = "RELATED_QUESTIONS"
# `action_id` del evento del clic (el API lo exige en mayusculas, `InteractionIn`).
RELATED_ACTION_ID = "RELATED_QUESTION"
# Cuantos botones como maximo: mas de tres ya no es una sugerencia, es un menu.
MAX_RELATED = 3

_TRAILING_DECORATION = frozenset({"So", "Sk", "Sm", "Mn", "Cf", "Zs", "Po"})


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
    siempre es un chip. `title` es lo que se lee; `url` a donde va.
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


def related_questions(evidence: list[Fragment], candidates: list[Fragment]) -> list[str]:
    """Las otras preguntas del articulo que respondio, para ofrecer como botones.

    - El articulo es el del MEJOR fragmento de la evidencia (el que responde la pregunta).
    - Ese fragmento se excluye: es lo que se acaba de contestar. Los demas del mismo articulo
      entran por score, esten o no dentro de la evidencia (con la expansion por tema el
      redactor pudo verlos, pero el prompt le pide responder LA pregunta, no el articulo).
    - Solo fragmentos con pregunta (`question_of`): la introduccion no es un boton.
    - Nada de otros articulos: los botones son "mas sobre esto", no un menu del corpus.
    - `candidates` son todos los hits que trajo el indice (`RagResult.all_fragments`): el
      articulo de registro tiene 5 preguntas y el indice devuelve 8 candidatos, asi que en
      general estan todas; si alguna no vino, simplemente no se ofrece.
    """
    if not evidence:
        return []
    best = max(evidence, key=lambda f: f.score)
    topic = best.topic
    if not topic:
        return []
    best_question = question_of(best)
    seen: set[str] = set()
    if best_question:
        seen.add(best_question)
    pool = sorted(
        (f for f in candidates if f.topic == topic and f != best),
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


def related_metadata(questions: list[str]) -> dict | None:
    """La metadata del mensaje del bot que el widget dibuja como botones (MAPEO.md §3).

    Cada opcion lleva su `query`: es lo que va al RAG al hacer clic, y el servidor lo lee de
    AQUI (del mensaje persistido), no del payload del clic — editar el HTML no inventa
    consultas. Sin `flow_version`: no hay estado que versionar.
    """
    if not questions:
        return None
    return {
        "interaction": {
            "type": RELATED_QUESTIONS,
            "action_id": RELATED_ACTION_ID,
            "options": [
                {"label": question, "value": f"Q{index}", "query": question}
                for index, question in enumerate(questions, start=1)
            ],
        }
    }


def resolve_click(interaction: dict | None, last_bot_metadata: dict | None) -> str | None:
    """La consulta canonica del boton pulsado, si el clic corresponde a los botones que el
    bot dejo en su ULTIMO mensaje; None en cualquier otro caso (botones viejos, valor
    inventado, payload malformado). Un clic invalido no es un error: el mensaje sigue el
    pipeline como texto normal.
    """
    if not isinstance(interaction, dict) or interaction.get("action_id") != RELATED_ACTION_ID:
        return None
    offered = (last_bot_metadata or {}).get("interaction")
    if not isinstance(offered, dict) or offered.get("type") != RELATED_QUESTIONS:
        return None
    value = interaction.get("value")
    for option in offered.get("options") or []:
        if isinstance(option, dict) and option.get("value") == value:
            query = option.get("query")
            return str(query) if query else None
    return None
