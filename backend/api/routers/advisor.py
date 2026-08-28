"""Superficie del asesor (KAM/CAM) — `/advisor/*`. RF-012, RF-029, RF-031..RF-036, RF-038.

Contrato con la app del asesor (frontend/):
  GET  /advisor/me                                    → el asesor de este token (auto-alta RF-006)
  GET  /advisor/conversations?status=&mine=&limit=    → bandeja (RF-032): pendientes primero
  GET  /advisor/conversations/{id}                    → conversacion + contexto del usuario
  GET  /advisor/conversations/{id}/messages           → ultimos N (RF-033); `before=` pagina hacia
                                                        atras (RF-012); `after=` solo lo nuevo.
                                                        Abrirlo consume los no leidos (RF-035)
  POST /advisor/conversations/{id}/take               → toma atomica (RF-029 / AC-005); 409 si
                                                        otro la tiene, con el estado actual
  POST /advisor/conversations/{id}/messages           → 201, idempotente por client_message_id
                                                        (RF-034 / RF-038 / AC-006); 409 si no es mia
  POST /advisor/conversations/{id}/close              → cierre minimo del caso (RF-031, sin ticket)

Autenticacion (T1): el JWT de Cognito lo valida el authorizer del API Gateway; aqui solo se
leen los claims del evento (core/auth.py) y se resuelve el asesor (advisors/service.py). En
local, backend/api/dev_auth.py imita al authorizer con `ADVISOR_DEV_AUTH=1`.

Campos del usuario que se exponen: los que ya guarda la conversacion (nombre, correo, empresa,
id VMC). D-010 sigue abierta — si decide menos campos, se recortan en `ConversationDetail`.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from backend.advisors import service as advisors
from backend.advisors.models import Advisor
from backend.api.routers.chat import MessageOut
from backend.conversations import repository, service
from backend.conversations.models import Conversation, ConversationStatus
from backend.core import auth

router = APIRouter(prefix="/advisor", tags=["advisor"])


# ───────────────────────────────────── Dependencias ─────────────────────────────────────


def get_current_advisor(claims: auth.CurrentClaims) -> Advisor:
    try:
        return advisors.resolve_advisor(claims)
    except advisors.AdvisorDisabled as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Asesor deshabilitado") from exc


CurrentAdvisor = Annotated[Advisor, Depends(get_current_advisor)]


def _load(conversation_id: str) -> Conversation:
    conversation = repository.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversacion no encontrada")
    return conversation


# ───────────────────────────────── Modelos de entrada/salida ─────────────────────────────────


class AdvisorOut(BaseModel):
    advisor_id: str
    name: str | None = None
    email: str | None = None
    role: str
    status: str
    last_login_at: str | None = None

    @classmethod
    def from_model(cls, advisor: Advisor) -> "AdvisorOut":
        return cls(**advisor.model_dump(include=set(cls.model_fields)))


class ConversationDetail(BaseModel):
    """Espejo de `Conversation` (frontend/src/lib/types.ts): la bandeja y la vista usan lo mismo."""

    conversation_id: str
    user_type: str
    status: str
    channel: str
    bot_enabled: bool
    user_id: str | None = None
    user_name: str | None = None
    user_email: str | None = None
    user_company: str | None = None
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

    @classmethod
    def from_model(cls, conversation: Conversation) -> "ConversationDetail":
        return cls(**conversation.model_dump(include=set(cls.model_fields)))


class InboxOut(BaseModel):
    conversations: list[ConversationDetail]


class ThreadOut(BaseModel):
    conversation: ConversationDetail
    messages: list[MessageOut]
    # SK del mensaje mas antiguo entregado: se pasa como `before` para la pagina anterior.
    next_before: str | None
    has_more: bool
    # SK del ultimo mensaje: se pasa como `after` en el sondeo.
    next_after: str | None


class AdvisorMessageIn(BaseModel):
    client_message_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    content: str = Field(min_length=1, max_length=20_000)


class MessageCreated(BaseModel):
    message: MessageOut
    duplicate: bool


class ConflictDetail(BaseModel):
    detail: str
    conversation: dict[str, Any]


# ──────────────────────────────────────── Rutas ────────────────────────────────────────


@router.get("/me", response_model=AdvisorOut)
def me(advisor: CurrentAdvisor) -> AdvisorOut:
    return AdvisorOut.from_model(advisor)


@router.get("/conversations", response_model=InboxOut)
def inbox(
    advisor: CurrentAdvisor,
    status_filter: ConversationStatus | None = Query(default=None, alias="status"),
    mine: bool = Query(default=False, description="Solo los casos asignados a mi"),
    limit: int = Query(default=50, ge=1, le=100),
) -> InboxOut:
    conversations = service.list_inbox(
        status_filter, advisor_id=advisor.advisor_id if mine else None, limit=limit
    )
    return InboxOut(conversations=[ConversationDetail.from_model(c) for c in conversations])


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
def get_conversation(conversation_id: str, advisor: CurrentAdvisor) -> ConversationDetail:
    return ConversationDetail.from_model(_load(conversation_id))


@router.get("/conversations/{conversation_id}/messages", response_model=ThreadOut)
def thread(
    conversation_id: str,
    advisor: CurrentAdvisor,
    before: str | None = Query(default=None, max_length=128),
    after: str | None = Query(default=None, max_length=128),
    limit: int = Query(default=20, ge=1, le=100),
) -> ThreadOut:
    if before and after:
        raise HTTPException(422, "before y after son excluyentes")
    conversation = _load(conversation_id)
    messages, has_more = service.open_thread(
        conversation, before=before, after=after, limit=limit
    )
    if conversation.unread_count:
        conversation = conversation.model_copy(update={"unread_count": 0})
    return ThreadOut(
        conversation=ConversationDetail.from_model(conversation),
        messages=[MessageOut.from_model(m) for m in messages],
        next_before=messages[0].message_key if messages else before,
        has_more=has_more,
        next_after=messages[-1].message_key if messages else after,
    )


@router.post(
    "/conversations/{conversation_id}/take",
    response_model=ConversationDetail,
    responses={409: {"model": ConflictDetail}},
)
def take(conversation_id: str, advisor: CurrentAdvisor) -> ConversationDetail:
    conversation = _load(conversation_id)
    try:
        taken = service.take_conversation(
            conversation, advisor_id=advisor.advisor_id, advisor_name=advisor.name
        )
    except service.ConversationAlreadyTaken as exc:
        # AC-005: el que pierde recibe el estado actual, sin duplicar atencion.
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {
                "detail": "La conversacion ya esta tomada o no se puede tomar en su estado",
                "conversation": ConversationDetail.from_model(exc.conversation).model_dump(),
            },
        ) from exc
    return ConversationDetail.from_model(taken)


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=MessageCreated,
    status_code=status.HTTP_201_CREATED,
)
def post_message(
    conversation_id: str, body: AdvisorMessageIn, advisor: CurrentAdvisor
) -> MessageCreated:
    conversation = _load(conversation_id)
    try:
        message, created = service.post_advisor_message(
            conversation,
            advisor_id=advisor.advisor_id,
            advisor_name=advisor.name,
            client_message_id=body.client_message_id,
            content=body.content,
        )
    except service.NotAssignedToAdvisor as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Primero toma la conversacion para responder"
        ) from exc
    except (service.MessageTooLong, service.EmptyMessage) as exc:
        raise HTTPException(422, str(exc)) from exc
    return MessageCreated(message=MessageOut.from_model(message), duplicate=not created)


@router.post("/conversations/{conversation_id}/close", response_model=ConversationDetail)
def close(conversation_id: str, advisor: CurrentAdvisor) -> ConversationDetail:
    conversation = _load(conversation_id)
    try:
        closed = service.close_case(conversation, advisor_id=advisor.advisor_id)
    except service.NotAssignedToAdvisor as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Solo el asesor asignado puede cerrar el caso"
        ) from exc
    return ConversationDetail.from_model(closed)
