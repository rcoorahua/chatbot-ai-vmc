"""Modelos de SALIDA de la API, compartidos por los routers.

Cada `*Out` es una proyeccion de un modelo de dominio: `from_model` copia solo los campos
declarados, asi que agregar un atributo interno a `Conversation` no lo expone por accidente
(D-010: que campos del usuario ve el asesor sigue abierta; se recortan aqui). Antes cada
router tenia su copia del mismo `from_model` (auditoria 2026-09-06).

Los modelos de ENTRADA (cuerpos de POST/PATCH) viven en cada router: son parte de su contrato
y no se comparten.
"""

from typing import Any, Self

from pydantic import BaseModel

from backend.conversations.models import Message


class ProjectionModel(BaseModel):
    """Un modelo de salida que se construye tomando de un modelo de dominio SOLO los campos
    que declara."""

    @classmethod
    def from_model(cls, model: BaseModel) -> Self:
        return cls(**model.model_dump(include=set(cls.model_fields)))


class ConversationOut(ProjectionModel):
    """La conversacion como la ve el WIDGET (chat publico): sin datos del usuario ni del
    asesor, que el propio usuario ya conoce o no le corresponden."""

    conversation_id: str
    user_type: str
    kind: str
    status: str
    bot_enabled: bool
    title: str | None = None
    message_count: int
    last_message_preview: str | None = None
    last_message_at: str
    created_at: str
    updated_at: str
    closed_at: str | None = None


class ConversationDetail(ProjectionModel):
    """La conversacion como la ve el ASESOR (bandeja y vista): espejo de `Conversation` en
    frontend/src/lib/types.ts. Campos del usuario: los que ya guarda la conversacion (nombre,
    correo, empresa, id VMC y CUU). D-010 quedo cerrada (2026-09-07): el asesor ve el CUU
    para ubicar a la persona en VMC, y no se busca por el."""

    conversation_id: str
    user_type: str
    kind: str
    status: str
    channel: str
    bot_enabled: bool
    user_id: str | None = None
    user_name: str | None = None
    user_email: str | None = None
    user_cuu: str | None = None
    user_company: str | None = None
    # D-029: asunto del caso y de que hilo salio.
    title: str | None = None
    source_conversation_id: str | None = None
    assigned_advisor_id: str | None = None
    summary: str | None = None
    message_count: int
    unread_count: int
    last_message_preview: str | None = None
    last_message_at: str
    handoff_requested_at: str | None = None
    handoff_reason: str | None = None
    created_at: str
    updated_at: str
    closed_at: str | None = None
    closed_by: str | None = None


class MessageOut(ProjectionModel):
    message_id: str
    message_key: str
    sender_type: str
    sender_id: str | None = None
    message_type: str
    status: str
    content: str | None = None
    client_message_id: str | None = None
    attachment: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    created_at: str


class MessageAccepted(BaseModel):
    """Respuesta de un POST de mensaje (usuario o asesor). `duplicate` = era un reintento con
    el mismo `client_message_id` (RF-038): el cliente recibe el mensaje original."""

    message: MessageOut
    duplicate: bool


class AdvisorOut(ProjectionModel):
    advisor_id: str
    name: str | None = None
    email: str | None = None
    role: str
    status: str
    last_login_at: str | None = None


class TicketOut(ProjectionModel):
    """El ticket como lo ve la app del asesor. `classification_source` distingue lo que
    sugirio la regla de lo que confirmo una persona: es el dato con el que se evalua la
    propuesta de taxonomia antes de cerrar D-008."""

    ticket_id: str
    conversation_id: str
    status: str
    user_type: str
    user_id: str | None = None
    user_email: str | None = None
    user_cuu: str | None = None
    problem_type: str
    category: str
    priority: str
    tags: list[str]
    classification_source: str
    classification_rule: str | None = None
    title: str | None = None
    description: str | None = None
    collected_data: dict[str, Any]
    missing_data: list[str]
    handoff_reason: str | None = None
    assigned_advisor_id: str | None = None
    assigned_at: str | None = None
    resolution: str | None = None
    closed_by: str | None = None
    created_at: str
    updated_at: str
    closed_at: str | None = None


def page_cursors(
    messages: list[Message], *, before: str | None, after: str | None
) -> tuple[str | None, str | None]:
    """`(next_before, next_after)` de una pagina de mensajes: la SK del mas antiguo (para
    "ver anteriores") y la del ultimo (para el sondeo). Sin mensajes, se devuelven los cursores
    con los que se pidio, para que el cliente no pierda su posicion."""
    if not messages:
        return before, after
    return messages[0].message_key, messages[-1].message_key
