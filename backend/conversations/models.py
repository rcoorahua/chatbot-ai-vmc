"""Modelos Pydantic: Conversation y Message — el lenguaje del dominio.

Atributos segun REQUERIMENTS.md §1.3-1.4 mas los ajustes 1-3 de §1.11 (`unread_count`,
`wait_message_sent`, `expires_at` en Messages) y el ajuste 6 que introduce esta fase: `status`
en Messages, el "estado tecnico" que RF-008 exige por mensaje. Estados y tipos en ingles (T7).

Los modelos se convierten a item DynamoDB con `to_item()` (core/dynamo_model.py), que omite los
None a proposito: un atributo ausente no entra a los GSI.
"""

from enum import StrEnum
from typing import Any

from backend.core.dynamo_model import DynamoModel


class ConversationStatus(StrEnum):
    BOT_ATTENDING = "BOT_ATTENDING"
    PENDING_ADVISOR = "PENDING_ADVISOR"
    IN_ATTENTION = "IN_ATTENTION"
    # Con D-003 cerrada (una sola conversacion por usuario autenticado; lo que se cierra son
    # los tickets) este estado queda para la conversacion anonima al expirar su sesion y para
    # compatibilidad con RF-009. La conversacion autenticada vuelve a BOT_ATTENDING al cerrarse
    # el ticket, con un mensaje SYSTEM `TICKET_CLOSED` en el hilo.
    CLOSED = "CLOSED"


class UserType(StrEnum):
    AUTHENTICATED = "AUTHENTICATED"
    ANONYMOUS = "ANONYMOUS"


class SenderType(StrEnum):
    USER = "USER"
    BOT = "BOT"
    ADVISOR = "ADVISOR"
    SYSTEM = "SYSTEM"


class MessageType(StrEnum):
    TEXT = "TEXT"
    IMAGE = "IMAGE"
    SYSTEM = "SYSTEM"


class MessageStatus(StrEnum):
    """Estado tecnico del mensaje (RF-008): que paso con el despues de persistirlo.

    Un mensaje de USER nace RECEIVED (durable, pendiente del pipeline IA); el worker lo lleva a
    PROCESSED o FAILED. QUEUE_FAILED significa que se guardo pero no se pudo encolar: el
    mensaje no se pierde, pero nadie lo va a atender hasta re-encolarlo (alarma RNF-006).
    Los mensajes salientes (BOT/ADVISOR/SYSTEM) nacen DELIVERED: persistir es entregar.
    """

    RECEIVED = "RECEIVED"
    QUEUE_FAILED = "QUEUE_FAILED"
    PROCESSED = "PROCESSED"
    FAILED = "FAILED"
    DELIVERED = "DELIVERED"


class SystemEvent(StrEnum):
    """Eventos de auditoria que viajan como mensajes SYSTEM (RF-050, PLAN.md §4).

    El widget traduce el codigo a texto en español ("Ticket cerrado"), igual que Intercom
    muestra sus notas de sistema en el hilo. Los datos quedan en ingles (T7).
    """

    HANDOFF_REQUESTED = "HANDOFF_REQUESTED"
    ADVISOR_ASSIGNED = "ADVISOR_ASSIGNED"
    TICKET_OPENED = "TICKET_OPENED"
    TICKET_CLOSED = "TICKET_CLOSED"
    BOT_DISABLED = "BOT_DISABLED"
    BOT_ENABLED = "BOT_ENABLED"
    CONVERSATION_CLOSED = "CONVERSATION_CLOSED"


# Alias historico: el modelo base vive en core/dynamo_model.py.
_DynamoModel = DynamoModel


class Conversation(_DynamoModel):
    conversation_id: str
    user_type: UserType
    status: ConversationStatus = ConversationStatus.BOT_ATTENDING
    channel: str = "WEB"
    bot_enabled: bool = True
    user_id: str | None = None
    user_name: str | None = None
    user_email: str | None = None
    user_company: str | None = None
    assigned_advisor_id: str | None = None
    summary: str | None = None
    summary_updated_at: str | None = None
    message_count: int = 0
    unread_count: int = 0
    wait_message_sent: bool = False
    last_message_preview: str | None = None
    last_message_at: str
    handoff_requested_at: str | None = None
    handoff_reason: str | None = None
    created_at: str
    updated_at: str
    closed_at: str | None = None
    expires_at: int | None = None


class Message(_DynamoModel):
    conversation_id: str
    message_key: str
    message_id: str
    sender_type: SenderType
    sender_id: str | None = None
    message_type: MessageType = MessageType.TEXT
    status: MessageStatus
    content: str | None = None
    client_message_id: str | None = None
    attachment: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    created_at: str
    expires_at: int | None = None


def message_key_for(created_at: str, message_id: str) -> str:
    """SK de Messages: `created_at#message_id` (orden cronologico gratis, PLAN.md §4)."""
    return f"{created_at}#{message_id}"


# Prefijo del item marcador de idempotencia (ajuste 4 de §1.11). Ordena despues de cualquier
# timestamp (`C` > `2`), asi que los listados acotan la SK por arriba para no verlo.
IDEMPOTENCY_KEY_PREFIX = "CMID#"


def idempotency_key_for(client_message_id: str) -> str:
    return f"{IDEMPOTENCY_KEY_PREFIX}{client_message_id}"
