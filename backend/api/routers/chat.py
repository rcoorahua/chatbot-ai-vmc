"""Router publico del widget (`/chat/*`) — RF-001, RF-004, RF-005, RF-008 y AC-008.

Contrato con el widget (widget/subastin.js):
  POST /chat/sessions                              → identidad + conversacion + token de sesion
  GET  /chat/conversations/{id}                    → estado de la conversacion
  GET  /chat/conversations/{id}/messages?after=    → sondeo de mensajes nuevos (TD-001: polling)
  POST /chat/conversations/{id}/messages           → 202: persiste, encola el job IA (T8)

Toda ruta salvo la primera exige `Authorization: Bearer <token de sesion>` y el token esta
atado a UNA conversacion (D-002): pedir otra es 403 aunque exista. La identidad del usuario
nunca llega suelta en el body — solo dentro del JWT firmado por VMC (RNF-005, core/auth.py).
"""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from backend.conversations import repository, service
from backend.conversations.models import Conversation, Message, MessageStatus
from backend.core import auth, jobs
from backend.core.clock import utc_now_iso
from backend.core.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


# ───────────────────────────────── Modelos de entrada/salida ─────────────────────────────────


class ConversationOut(BaseModel):
    conversation_id: str
    user_type: str
    status: str
    bot_enabled: bool
    message_count: int
    last_message_at: str
    created_at: str
    updated_at: str

    @classmethod
    def from_model(cls, conversation: Conversation) -> "ConversationOut":
        return cls(**conversation.model_dump(include=set(cls.model_fields)))


class MessageOut(BaseModel):
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

    @classmethod
    def from_model(cls, message: Message) -> "MessageOut":
        return cls(**message.model_dump(include=set(cls.model_fields)))


class SessionIn(BaseModel):
    # JWT firmado por el servidor de VMC (D-001). Ausente = usuario anonimo (RF-001/RF-002).
    user_jwt: str | None = Field(default=None, max_length=4096)


class SessionUser(BaseModel):
    type: str
    name: str | None = None


class SessionLimits(BaseModel):
    """Limites que el widget necesita para no dejar escribir lo que el servidor va a rechazar.

    Viajan en la sesion en vez de estar copiados en el widget: son configuracion (RNF-007,
    `MAX_MESSAGE_CHARS`), y duplicar el numero en `widget/subastin.js` significaria que subir
    el limite en `.env` deja al widget cortando en el valor viejo, sin que nada avise.
    """

    max_message_chars: int


class SessionOut(BaseModel):
    token: str
    expires_at: int
    user: SessionUser
    conversation: ConversationOut
    created: bool
    limits: SessionLimits


class InteractionIn(BaseModel):
    """El evento estructurado de un quick reply (D-028, MAPEO.md §3).

    El API solo lo PERSISTE en la metadata del mensaje (T3: la API encola y responde 202);
    quien lo valida contra el paso vigente del flujo es el worker. Un evento invalido o de
    una version vieja se degrada a texto normal — nunca es un error para el usuario.
    """

    action_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Z0-9_]+$")
    value: str = Field(min_length=1, max_length=64, pattern=r"^[A-Z0-9_]+$")
    flow_version: int = Field(ge=1, le=1_000_000)
    source_message_id: str | None = Field(default=None, max_length=64)


class MessageIn(BaseModel):
    # Lo genera el widget (UUID); repetirlo en un reintento es lo que evita duplicados (RF-038).
    client_message_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    # Tope generoso de transporte; el limite real (RF-014, configurable) lo aplica el servicio.
    content: str = Field(min_length=1, max_length=20_000)
    # Presente solo cuando el mensaje nacio de un click de quick reply.
    interaction: InteractionIn | None = None


class MessageAccepted(BaseModel):
    message: MessageOut
    duplicate: bool


class MessagesOut(BaseModel):
    messages: list[MessageOut]
    # SK del ultimo mensaje entregado: el widget lo devuelve como `after` en el siguiente sondeo.
    next_after: str | None


# ──────────────────────────────────────── Rutas ────────────────────────────────────────


@router.post("/sessions", response_model=SessionOut, status_code=status.HTTP_201_CREATED)
def create_session(body: SessionIn) -> SessionOut:
    identity: auth.VmcIdentity | None = None
    if body.user_jwt:
        try:
            identity = auth.verify_vmc_identity(body.user_jwt)
        except auth.IdentityError as exc:
            # Un JWT invalido NO degrada a anonimo en silencio: el widget debe enterarse de que
            # la identidad no paso, porque un usuario logueado tratado como anonimo perderia
            # su historial sin explicacion.
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED, f"Identidad VMC invalida: {exc}"
            ) from exc
        except auth.IdentityConfigurationError as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    conversation, created = service.open_conversation(identity)
    session = auth.new_session(
        user_type=str(conversation.user_type),
        conversation_id=conversation.conversation_id,
        user_id=conversation.user_id,
        user_name=conversation.user_name,
    )
    try:
        token = auth.issue_session_token(session)
    except auth.IdentityConfigurationError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    return SessionOut(
        token=token,
        expires_at=session.expires_at,
        user=SessionUser(type=session.user_type, name=session.user_name),
        conversation=ConversationOut.from_model(conversation),
        created=created,
        limits=SessionLimits(max_message_chars=get_settings().max_message_chars),
    )


def _owned_conversation(session: auth.ChatSession, conversation_id: str) -> Conversation:
    if conversation_id != session.conversation_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Esta conversacion no es de tu sesion")
    conversation = repository.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversacion no encontrada")
    return conversation


@router.get("/conversations/{conversation_id}", response_model=ConversationOut)
def get_conversation(conversation_id: str, session: auth.CurrentSession) -> ConversationOut:
    return ConversationOut.from_model(_owned_conversation(session, conversation_id))


@router.get("/conversations/{conversation_id}/messages", response_model=MessagesOut)
def list_messages(
    conversation_id: str,
    session: auth.CurrentSession,
    after: str | None = Query(default=None, max_length=128),
    limit: int = Query(default=50, ge=1, le=100),
) -> MessagesOut:
    _owned_conversation(session, conversation_id)
    messages = service.list_messages(conversation_id, after=after, limit=limit)
    return MessagesOut(
        messages=[MessageOut.from_model(message) for message in messages],
        next_after=messages[-1].message_key if messages else after,
    )


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=MessageAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def post_message(
    conversation_id: str, body: MessageIn, session: auth.CurrentSession
) -> MessageAccepted:
    conversation = _owned_conversation(session, conversation_id)
    try:
        message, created = service.post_user_message(
            conversation,
            client_message_id=body.client_message_id,
            content=body.content,
            sender_id=session.user_id,
            metadata=(
                {"interaction": body.interaction.model_dump(exclude_none=True)}
                if body.interaction
                else None
            ),
        )
    except service.MessageTooLong as exc:
        raise HTTPException(422, str(exc)) from exc
    except service.EmptyMessage as exc:
        raise HTTPException(422, str(exc)) from exc
    except service.RateLimited as exc:
        # `Retry-After` es el estandar de 429: el widget lo respeta en vez de reintentar solo.
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Estas enviando mensajes muy rapido. Espera un momento.",
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc
    except repository.ConversationNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversacion no encontrada") from exc

    # Un reintento no vuelve a encolar: el job del mensaje original ya esta en camino.
    if created:
        _enqueue_or_mark_failed(message)
    return MessageAccepted(message=MessageOut.from_model(message), duplicate=not created)


def _enqueue_or_mark_failed(message: Message) -> None:
    """RNF-003 manda: el mensaje ya es durable, asi que un fallo de la cola no es un 500 para
    el usuario. Se marca el mensaje para que un barrido lo re-encole y se deja rastro en logs
    (alarma pendiente en RNF-006)."""
    job = jobs.AIJob(
        conversation_id=message.conversation_id,
        message_id=message.message_id,
        message_key=message.message_key,
        requested_at=utc_now_iso(),
    )
    try:
        jobs.enqueue_ai_job(job)
    except Exception:  # noqa: BLE001 — cualquier fallo de SQS termina en el mismo estado
        logger.exception(
            "No se pudo encolar el job IA", extra={"message_id": message.message_id}
        )
        repository.update_message_status(
            message.conversation_id, message.message_key, MessageStatus.QUEUE_FAILED
        )
        message.status = MessageStatus.QUEUE_FAILED
