"""El `extra` de los logs del worker: siempre con la conversacion y el mensaje (RNF-006)."""

import logging

from backend.conversations.models import Conversation, Message

logger = logging.getLogger("backend.workers.ai_worker")


def ctx(conversation: Conversation, message: Message | None = None, **extra) -> dict:
    """`extra={...}` para `logger.*`: conversation_id, message_id (si hay) y lo que se sume.
    Antes cada log armaba el mismo dict a mano (10+ sitios)."""
    data: dict = {"conversation_id": conversation.conversation_id}
    if message is not None:
        data["message_id"] = message.message_id
    data.update(extra)
    return data


def log_skip(conversation: Conversation, message: Message, reason: str) -> None:
    """Un job que no responde (debounce, carrera de flujo): queda en el log con su motivo."""
    logger.debug("ai.debounce.skip", extra=ctx(conversation, message, reason=reason))
