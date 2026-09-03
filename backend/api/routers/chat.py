"""Router publico del widget (`/chat/*`) — RF-001, RF-003, RF-004, RF-005, RF-008, AC-008.

Contrato con el widget (widget/subastin.js):
  POST /chat/sessions                              → identidad + hilo del bot + token de sesion
  GET  /chat/conversations                         → hilo + casos del usuario (D-029)
  GET  /chat/conversations/{id}                    → estado de la conversacion
  GET  /chat/conversations/{id}/messages           → sin cursor: los ultimos N (+ estado de la
                                                     conversacion); `after=` sondeo de lo
                                                     nuevo (TD-001: polling); `before=` pagina
                                                     hacia atras
  POST /chat/conversations/{id}/messages           → 202: persiste, encola el job IA (T8);
                                                     409 si la conversacion esta cerrada
  POST /chat/conversations/{id}/handoff            → 201: formulario de asesor (D-029): abre
                                                     un caso (autenticado) o deriva en el sitio
                                                     (anonimo, RF-003)

Toda ruta salvo la primera exige `Authorization: Bearer <token de sesion>`. Autorizacion: el
autenticado ve todo lo suyo (hilo y casos, por `user_id`); el anonimo solo la conversacion
atada a su token. Otra cosa es 403 aunque exista. La identidad del usuario nunca llega
suelta en el body — solo dentro del JWT firmado por VMC (RNF-005, core/auth.py).
"""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from backend.agent import prompts, quota
from backend.conversations import forms, repository, service
from backend.conversations.models import Conversation, Message, MessageStatus, UserType
from backend.core import auth, jobs
from backend.core.clock import utc_now_iso
from backend.core.config import get_settings
from backend.tickets import service as tickets

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


# ───────────────────────────────── Modelos de entrada/salida ─────────────────────────────────


class ConversationOut(BaseModel):
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
    # Estado vigente de la conversacion en cada sondeo: el widget decide con esto la cadencia,
    # el indicador de "escribiendo" y si el compositor sigue abierto (D-029).
    conversation: ConversationOut
    messages: list[MessageOut]
    # SK del ultimo mensaje entregado: el widget lo devuelve como `after` en el siguiente sondeo.
    next_after: str | None
    # SK del mas antiguo entregado y si hay mas detras: para "ver mensajes anteriores".
    next_before: str | None = None
    has_more: bool = False


class ConversationsOut(BaseModel):
    conversations: list[ConversationOut]


class HandoffIn(BaseModel):
    """Lo que el usuario contesto en la tarjeta de formulario (conversations/forms.py valida
    de verdad; aqui solo topes de transporte)."""

    subject: str = Field(min_length=1, max_length=1_000)
    detail: str = Field(min_length=1, max_length=20_000)
    name: str | None = Field(default=None, max_length=1_000)
    email: str | None = Field(default=None, max_length=1_000)
    phone: str | None = Field(default=None, max_length=200)


class HandoffOut(BaseModel):
    # La conversacion que espera al asesor: el caso nuevo (autenticado) o la misma (anonimo).
    conversation: ConversationOut


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

    # DETAILS.md §4.2: falla ANTES de abrir la conversacion si falta la clave de sesion — si no,
    # un anonimo sin SESSION_SIGNING_KEY dejaba una fila huerfana en cada intento (el 503 llegaba
    # recien al firmar el token, con la conversacion ya creada).
    try:
        auth.ensure_session_signing_configured()
    except auth.IdentityConfigurationError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    conversation, created = service.open_conversation(identity)
    session = auth.new_session(
        user_type=str(conversation.user_type),
        conversation_id=conversation.conversation_id,
        user_id=conversation.user_id,
        user_name=conversation.user_name,
    )
    token = auth.issue_session_token(session)  # ya validado arriba: no puede fallar por config

    return SessionOut(
        token=token,
        expires_at=session.expires_at,
        user=SessionUser(type=session.user_type, name=session.user_name),
        conversation=ConversationOut.from_model(conversation),
        created=created,
        limits=SessionLimits(max_message_chars=get_settings().max_message_chars),
    )


def _owned_conversation(session: auth.ChatSession, conversation_id: str) -> Conversation:
    # El 403 del ajeno sale ANTES de leer nada cuando la regla es por id (anonimo); para el
    # autenticado hay que leer la fila para comparar el `user_id`. Un id inexistente del
    # anonimo es 403, no 404: no se confirma que exista lo que no es suyo.
    if not session.is_authenticated and conversation_id != session.conversation_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Esta conversacion no es de tu sesion")
    conversation = repository.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversacion no encontrada")
    if not service.owns(session, conversation):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Esta conversacion no es de tu sesion")
    return conversation


@router.get("/conversations", response_model=ConversationsOut)
def list_conversations(session: auth.CurrentSession) -> ConversationsOut:
    return ConversationsOut(
        conversations=[ConversationOut.from_model(c) for c in service.list_conversations(session)]
    )


@router.get("/conversations/{conversation_id}", response_model=ConversationOut)
def get_conversation(conversation_id: str, session: auth.CurrentSession) -> ConversationOut:
    return ConversationOut.from_model(_owned_conversation(session, conversation_id))


@router.get("/conversations/{conversation_id}/messages", response_model=MessagesOut)
def list_messages(
    conversation_id: str,
    session: auth.CurrentSession,
    after: str | None = Query(default=None, max_length=128),
    before: str | None = Query(default=None, max_length=128),
    limit: int = Query(default=50, ge=1, le=100),
) -> MessagesOut:
    if before and after:
        raise HTTPException(422, "before y after son excluyentes")
    conversation = _owned_conversation(session, conversation_id)
    if after:
        messages = service.list_messages(conversation_id, after=after, limit=limit)
        has_more = False
    else:
        messages, has_more = service.latest_messages(conversation_id, before=before, limit=limit)
    return MessagesOut(
        conversation=ConversationOut.from_model(conversation),
        messages=[MessageOut.from_model(message) for message in messages],
        next_after=messages[-1].message_key if messages else after,
        next_before=messages[0].message_key if messages else before,
        has_more=has_more,
    )


@router.post(
    "/conversations/{conversation_id}/handoff",
    response_model=HandoffOut,
    status_code=status.HTTP_201_CREATED,
)
def request_handoff(
    conversation_id: str, body: HandoffIn, session: auth.CurrentSession, request: Request
) -> HandoffOut:
    """El usuario envio el formulario de asesor (D-029). Autenticado: 201 con el CASO nuevo;
    anonimo: 201 con su misma conversacion ya derivada (RF-003). 409 si no se puede derivar
    desde aqui (ya derivada, cerrada, o tope de casos); 422 con `field` si un dato no pasa;
    429 si la IP anonima ya pidio demasiados asesores hoy."""
    conversation = _owned_conversation(session, conversation_id)
    anonymous = conversation.user_type == UserType.ANONYMOUS
    form = forms.HandoffForm(
        subject=body.subject, detail=body.detail, name=body.name, email=body.email,
        phone=body.phone,
    )
    # DETAILS.md §4.5 / Paso 6: un formulario invalido no debe quemar el cupo diario de la IP
    # anonima. Se valida ANTES del 429 — la limpieza real (y su reuso) sigue dentro de
    # service.request_handoff, esto solo adelanta el 422 para que el rechazo no tenga costo.
    try:
        forms.validate_handoff_form(
            form,
            anonymous=anonymous,
            needs_email=not anonymous and not conversation.user_email,
            max_detail_chars=get_settings().max_message_chars,
        )
    except forms.FormValidationError as exc:
        raise HTTPException(422, {"detail": str(exc), "field": exc.field}) from exc
    if anonymous:
        ip_hash = quota.hash_ip(_client_ip(request))
        limit = get_settings().anon_handoffs_per_ip_per_day
        if ip_hash and not quota.take_daily_slot(f"HANDOFF#IP#{ip_hash}", limit=limit):
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "Ya recibimos varias solicitudes de asesor desde tu conexion hoy. "
                "Crea tu cuenta en VMC para continuar.",
                headers={"Retry-After": "3600"},
            )
    confirmation = (
        prompts.HANDOFF_ANON_CONFIRMATION if anonymous else prompts.HANDOFF_CASE_CONFIRMATION
    )
    try:
        waiting = service.request_handoff(conversation, form, confirmation=confirmation)
    except forms.FormValidationError as exc:
        raise HTTPException(422, {"detail": str(exc), "field": exc.field}) from exc
    except service.TooManyOpenCases as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Ya tienes {exc.limit} casos abiertos. Continua en uno de ellos o espera a que "
            "un asesor lo cierre.",
        ) from exc
    except service.HandoffNotAllowed as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Esta conversacion ya esta con el equipo o cerrada"
        ) from exc
    # RF-023: el trabajo humano se registra como ticket. Va DESPUES de derivar y fuera de la
    # transaccion a proposito: la conversacion ya es durable y el usuario ya vio su
    # confirmacion, asi que un fallo aqui no puede convertirse en un error para el. La red de
    # seguridad es `tickets.ensure_ticket`, que corre cuando un asesor abre o toma el caso.
    ticket_id = None
    try:
        ticket_id = tickets.open_ticket(waiting, description=body.detail).ticket_id
    except Exception:  # noqa: BLE001 — ver comentario: nunca rompe el handoff del usuario
        logger.exception(
            "No se pudo abrir el ticket del caso",
            extra={"conversation_id": waiting.conversation_id},
        )
    logger.info(
        "chat.handoff",
        extra={
            "conversation_id": conversation.conversation_id,
            "case_id": waiting.conversation_id,
            "ticket_id": ticket_id,
            "anonymous": anonymous,
        },
    )
    return HandoffOut(conversation=ConversationOut.from_model(waiting))


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=MessageAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def post_message(
    conversation_id: str, body: MessageIn, session: auth.CurrentSession, request: Request
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
    except service.ConversationClosed as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Esta conversacion esta cerrada. Abre una nueva."
        ) from exc
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
        _enqueue_or_mark_failed(message, ip_hash=quota.hash_ip(_client_ip(request)))
    return MessageAccepted(message=MessageOut.from_model(message), duplicate=not created)


def _client_ip(request: Request) -> str | None:
    """IP del cliente: en Lambda la deja API Gateway en el evento (Mangum la expone en el
    scope); en local, la conexion directa de uvicorn. Solo se usa hasheada (T-09/D-027)."""
    event = request.scope.get("aws.event") or {}
    source_ip = (
        event.get("requestContext", {}).get("http", {}).get("sourceIp")
        if isinstance(event, dict)
        else None
    )
    if source_ip:
        return source_ip
    return request.client.host if request.client else None


def _enqueue_or_mark_failed(message: Message, *, ip_hash: str | None = None) -> None:
    """RNF-003 manda: el mensaje ya es durable, asi que un fallo de la cola no es un 500 para
    el usuario. Se marca el mensaje para que un barrido lo re-encole y se deja rastro en logs
    (alarma pendiente en RNF-006)."""
    job = jobs.AIJob(
        conversation_id=message.conversation_id,
        message_id=message.message_id,
        message_key=message.message_key,
        requested_at=utc_now_iso(),
        ip_hash=ip_hash,
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
