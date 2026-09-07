"""El flujo guiado (D-028) tal como esta en la fila de Conversations: si hay uno, si sigue
vigente, como limpiarlo y como releer la fila cuando `flow_version` acaba de cambiar."""

from backend.agent import flows
from backend.conversations import service
from backend.conversations.models import Conversation
from backend.core.clock import utc_now_iso


def current_flow(
    conversation: Conversation,
) -> tuple[flows.FlowDefinition, flows.FlowStep, bool] | None:
    """(definicion, paso, vigente) del flujo activo; None si no hay flujo o ya no existe la
    definicion (un deploy pudo retirarla: el estado viejo no debe romper nada)."""
    if not conversation.active_flow:
        return None
    definition = flows.FLOWS.get(conversation.active_flow)
    step = definition.step(conversation.flow_step or "") if definition else None
    if definition is None or step is None:
        return None
    expired = bool(conversation.flow_expires_at) and conversation.flow_expires_at <= utc_now_iso()
    return definition, step, not expired


def awaiting_slot(conversation: Conversation) -> bool:
    """Hay un flujo del corpus vigente esperando que el usuario elija (botones en pantalla).
    La confirmacion de asesor no cuenta: la resuelve `guided.settle_handoff_confirm` antes de
    que esto se consulte."""
    active = current_flow(conversation)
    return active is not None and active[2] and active[0].name != flows.HANDOFF_CONFIRM


def refreshed(conversation: Conversation) -> Conversation:
    """La fila fresca tras limpiar un flujo: `flow_version` acaba de cambiar y cualquier
    transicion hecha con la copia vieja pierde la carrera por condicion — y un
    `replies.offer_flow_step` que la pierde no publica nada: el usuario se queda sin respuesta."""
    return service.get_conversation(conversation.conversation_id) or conversation


def clear_flow_if_active(conversation: Conversation) -> None:
    """Limpieza best-effort: si otro proceso movio el flujo primero, no hay nada que hacer."""
    if conversation.active_flow:
        service.clear_flow(conversation)
