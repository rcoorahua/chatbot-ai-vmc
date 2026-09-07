"""Accesores sobre la ventana de contexto (RF-013 / D-004): la rafaga que se responde, el
ultimo mensaje del bot con sus distintas lecturas, la consulta previa y el historial para el
redactor. Funciones puras sobre `list[Message]` (salvo `is_repeat`, que lee el reloj y la
configuracion).

Los tres "ultimo mensaje del bot" NO son el mismo: `last_bot_text` es cualquier respuesta;
`last_bot_open_question` solo si no dejo botones esperando; `last_bot_metadata` solo si
esta justo antes de la rafaga actual (una nota de sistema o un asesor en medio invalidan sus
botones). Antes eran cuatro funciones con nombres parecidos repartidas por el worker.
"""

from backend.agent import followups, prompts, trivial
from backend.conversations import forms
from backend.conversations.models import Message, SenderType
from backend.core.clock import minutes_ago_iso
from backend.core.config import get_settings
from backend.core.metadata import InteractionType, interaction_of, interaction_type

# Interacciones que dejan al bot ESPERANDO una respuesta estructurada: los botones de un
# flujo (o el si/no del asesor) y el formulario. Las preguntas hermanas (RELATED_QUESTIONS)
# y un enlace (LINKS) NO cuentan: son sugerencias sin estado, y desde D-031 van bajo toda
# respuesta con evidencia — si cerraran la pregunta, un "listo" o "y luego?" nunca seria
# continuacion.
AWAITING_ANSWER = frozenset({str(InteractionType.QUICK_REPLIES), forms.HANDOFF_FORM})


def trailing_user_block(window: list[Message]) -> list[Message]:
    """Los mensajes USER consecutivos al final del hilo: la rafaga que se responde junta."""
    block: list[Message] = []
    for item in reversed(window):
        if item.sender_type != SenderType.USER:
            break
        block.append(item)
    return list(reversed(block))


def is_repeat(text: str, window: list[Message], block_keys: list[str]) -> bool:
    """D-006: el mismo texto ya fue enviado (y atendido) hace poco. Solo mira mensajes USER
    anteriores al bloque actual: los del bloque son la misma rafaga, no una repeticion."""
    cutoff = minutes_ago_iso(get_settings().trivial_repeat_window_minutes)
    for item in window:
        if item.message_key in block_keys or item.sender_type != SenderType.USER:
            continue
        if item.created_at >= cutoff and trivial.same_message(item.content or "", text):
            return True
    return False


def already_warned_repeat(window: list[Message]) -> bool:
    """El aviso de repeticion sale una vez: a la segunda repeticion, silencio (el mensaje
    queda guardado igual)."""
    return last_bot_text(window) == prompts.TRIVIAL_REPEAT_RESPONSE


def _last_bot(window: list[Message]) -> Message | None:
    for item in reversed(window):
        if item.sender_type == SenderType.BOT and item.content:
            return item
    return None


def last_bot_text(window: list[Message]) -> str | None:
    last = _last_bot(window)
    return last.content if last else None


def last_bot_open_question(window: list[Message]) -> str | None:
    """El ultimo mensaje del bot, SOLO si era una pregunta abierta.

    Un mensaje con botones que ESPERAN respuesta (los de un flujo, el si/no del asesor, el
    formulario) tambien termina en "?", pero es una pregunta ESTRUCTURADA: sus respuestas
    validas las resuelve la maquinaria de flujos, y cualquier otra cosa que escriba el usuario
    es un tema nuevo, no la continuacion del anterior. Devolverla aqui hacia que "mejor dime
    cuanto es la comision", escrito despues de "¿quieres un asesor?", heredara el tema viejo
    y se buscara la pregunta equivocada.
    """
    last = _last_bot(window)
    if last is None or interaction_type(last.metadata) in AWAITING_ANSWER:
        return None
    return last.content


def last_bot_metadata(window: list[Message], block_keys: list[str]) -> dict | None:
    """La metadata del ultimo mensaje del bot justo antes de la rafaga actual: ahi estan los
    botones de preguntas hermanas (D-030) contra los que se valida un clic. Se lee del
    mensaje persistido, nunca del payload del clic. Una nota de sistema o un asesor en medio
    significan que esos botones ya no valen."""
    for item in reversed(window):
        if item.message_key in block_keys:
            continue
        return item.metadata if item.sender_type == SenderType.BOT else None
    return None


def previous_user_texts(window: list[Message], block_keys: list[str]) -> list[str]:
    """Lo que el usuario escribio ANTES de la rafaga actual, en orden cronologico. Es de donde
    `followups` saca la pregunta que da tema a una continuacion."""
    return [
        item.content
        for item in window
        if item.sender_type == SenderType.USER
        and item.message_key not in block_keys
        and item.content
    ]


def previous_query(window: list[Message], block_keys: list[str]) -> str | None:
    """La consulta que sostiene una continuacion: la que dio evidencia a la ultima respuesta
    del bot (viaja en su metadata, `followups.RAG_QUERY_KEY`) y, si esa respuesta no la trae
    (fija, con botones, o anterior a este campo), la ultima pregunta del usuario del historial.

    Preferir la de la respuesta cubre dos casos que el historial no cubre: un paso de flujo
    (D-028), cuya evidencia salio de la consulta canonica y no del texto del boton ("Oferta
    En Vivo" recupera peor), y una explicacion de varios "si" seguidos, donde la pregunta
    original ya quedo fuera de la mirada hacia atras de `last_user_question`.
    """
    for item in reversed(window):
        if item.message_key in block_keys or item.sender_type != SenderType.BOT:
            continue
        query = (item.metadata or {}).get(followups.RAG_QUERY_KEY)
        if query:
            return str(query)
        break  # la ultima respuesta del bot no salio del indice: decide el historial
    return followups.last_user_question(previous_user_texts(window, block_keys))


def history(window: list[Message], block_keys: list[str]) -> list[dict[str, str]]:
    """La ventana como turnos user/assistant para el redactor, sin el bloque actual (ese viaja
    como el mensaje) y sin notas SYSTEM (son eventos, no conversacion)."""
    turns: list[dict[str, str]] = []
    for item in window:
        if item.message_key in block_keys or not item.content:
            continue
        if item.sender_type == SenderType.USER:
            turns.append({"role": "user", "content": item.content})
        elif item.sender_type in (SenderType.BOT, SenderType.ADVISOR):
            turns.append({"role": "assistant", "content": item.content})
    return turns


def clicked_interaction(message: Message) -> dict | None:
    """El evento estructurado (quick reply, pregunta hermana, boton de asesor) que viajo con el
    mensaje del usuario, o None."""
    return interaction_of(message.metadata)
