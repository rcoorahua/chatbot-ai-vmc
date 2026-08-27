"""Orquestacion del dominio conversacion (SIN llamar integraciones — regla de backend/__init__.py).

Reglas de negocio que aplica esta fase (cerradas el 2026-08-27, ver CLAUDE.md):
- D-002: UNA conversacion activa por usuario, autenticado o anonimo.
- D-003: la del usuario autenticado es permanente — no se crea otra, no se "reabre"; el
  historial que se cierra son los tickets, que quedan como eventos SYSTEM dentro del hilo.
- RF-004 / D-018: la del anonimo vive lo que dure su sesion; nunca se recupera.
- RF-014: el largo del mensaje se limita por configuracion (valor provisional hasta D-005).

Lo que NO hace: encolar el job de IA. Eso lo compone la entrada (api/routers/chat.py) con
core/jobs.py, para que el dominio no dependa de SQS.
"""

import uuid

from backend.conversations import repository
from backend.conversations.models import (
    Conversation,
    ConversationStatus,
    Message,
    MessageStatus,
    MessageType,
    SenderType,
    SystemEvent,
    UserType,
    message_key_for,
)
from backend.core.auth import VmcIdentity
from backend.core.clock import utc_now_iso
from backend.core.config import get_settings

# Namespace fijo para derivar el id de la conversacion del usuario autenticado. Cambiarlo
# "perderia" todas las conversaciones existentes (seguirian en la tabla, pero nadie las
# buscaria por ese id).
_USER_CONVERSATION_NAMESPACE = uuid.UUID("5b1c6f2e-9d0a-4c77-8a2f-3e6d1b9f0c41")


class EmptyMessage(ValueError):
    pass


class MessageTooLong(ValueError):
    def __init__(self, limit: int) -> None:
        super().__init__(f"el mensaje supera el maximo de {limit} caracteres")
        self.limit = limit


def conversation_id_for_user(user_id: str) -> str:
    """Id determinista de la unica conversacion de un usuario autenticado (D-002 + D-003).

    Derivarlo del `user_id` en vez de buscarlo por GSI hace atomica la regla "maximo 1": dos
    pestañas que abren el chat a la vez intentan crear el MISMO item y la creacion condicional
    deja pasar solo a una. Si D-002 cambiara a N conversaciones, esto vuelve a ser aleatorio y
    la busqueda pasa a GSI1.
    """
    return str(uuid.uuid5(_USER_CONVERSATION_NAMESPACE, f"vmc-user:{user_id}"))


def open_conversation(identity: VmcIdentity | None) -> tuple[Conversation, bool]:
    """La conversacion de esta sesion: nueva para el anonimo, la de siempre para el
    autenticado. Devuelve `(conversacion, se_creo_ahora)`."""
    now = utc_now_iso()
    if identity is None:
        conversation = Conversation(
            conversation_id=str(uuid.uuid4()),
            user_type=UserType.ANONYMOUS,
            last_message_at=now,
            created_at=now,
            updated_at=now,
        )
        repository.create_conversation(conversation)
        return conversation, True

    conversation_id = conversation_id_for_user(identity.user_id)
    existing = repository.get_conversation(conversation_id)
    if existing is None:
        conversation = Conversation(
            conversation_id=conversation_id,
            user_type=UserType.AUTHENTICATED,
            user_id=identity.user_id,
            user_name=identity.name,
            user_email=identity.email,
            last_message_at=now,
            created_at=now,
            updated_at=now,
        )
        if repository.create_conversation(conversation):
            return conversation, True
        existing = repository.get_conversation(conversation_id)
        if existing is None:  # pragma: no cover — solo si la tabla se borra entre dos lecturas
            raise repository.ConversationNotFound(conversation_id)

    if _profile_changed(existing, identity):
        repository.update_user_profile(
            conversation_id, user_name=identity.name, user_email=identity.email, updated_at=now
        )
        existing = existing.model_copy(
            update={
                "user_name": identity.name or existing.user_name,
                "user_email": identity.email or existing.user_email,
                "updated_at": now,
            }
        )
    return existing, False


def _profile_changed(conversation: Conversation, identity: VmcIdentity) -> bool:
    """VMC manda; si el usuario cambio de nombre o correo, la copia local se actualiza."""
    return (identity.name is not None and identity.name != conversation.user_name) or (
        identity.email is not None and identity.email != conversation.user_email
    )


def post_user_message(
    conversation: Conversation,
    *,
    client_message_id: str,
    content: str,
    sender_id: str | None = None,
) -> tuple[Message, bool]:
    """Persiste el mensaje del usuario. `(mensaje, True)` si es nuevo; `(original, False)` si
    es un reintento con el mismo `client_message_id` (RF-038)."""
    text = content.strip()
    if not text:
        raise EmptyMessage("el mensaje esta vacio")
    limit = get_settings().max_message_chars
    if len(text) > limit:
        raise MessageTooLong(limit)

    now = utc_now_iso()
    message_id = str(uuid.uuid4())
    message = Message(
        conversation_id=conversation.conversation_id,
        message_key=message_key_for(now, message_id),
        message_id=message_id,
        sender_type=SenderType.USER,
        sender_id=sender_id,
        message_type=MessageType.TEXT,
        status=MessageStatus.RECEIVED,
        content=text,
        client_message_id=client_message_id,
        created_at=now,
    )
    # Solo cuenta como "no leido" para el asesor si el bot ya no atiende (RF-035): mientras la
    # IA responde sola, no hay nadie que deba leerlo.
    return repository.save_message_idempotent(
        message, count_as_unread=not conversation.bot_enabled
    )


def list_messages(
    conversation_id: str, *, after: str | None = None, limit: int | None = None
) -> list[Message]:
    page = limit or get_settings().messages_page_size
    return repository.list_messages(conversation_id, after=after, limit=page)


# ───────────────────────────── Lado del asesor (RF-012, RF-029..035) ─────────────────────────────
#
# Reglas cerradas con Aaron el 2026-08-27 (ver CLAUDE.md):
# - El asesor escribe SOLO en la conversacion que tomo (asignada a el, IN_ATTENTION). No hace
#   falta ticket para tomarla: la toma es a nivel conversacion; el ticket (F5) es el registro
#   del caso, no el permiso para atender.
# - Se puede tomar una PENDING_ADVISOR (handoff) y tambien una BOT_ATTENDING sin asesor: el
#   asesor interviene por su cuenta, como en Intercom. Tomarla apaga el bot.
# - "Cerrar caso" sin ticket (cierre minimo, provisional hasta F5): nota TICKET_CLOSED en el
#   hilo, la conversacion vuelve a BOT_ATTENDING con el bot encendido y sin asesor (D-003: la
#   conversacion nunca se cierra). Solo el asesor asignado cierra.
# - RF-035: abrir el hilo consume los no leidos.

_TAKEABLE_STATUSES = [ConversationStatus.PENDING_ADVISOR, ConversationStatus.BOT_ATTENDING]


class NotAssignedToAdvisor(PermissionError):
    """La conversacion no esta asignada a este asesor: no puede escribir ni cerrar."""


class ConversationAlreadyTaken(RuntimeError):
    def __init__(self, conversation: Conversation) -> None:
        super().__init__("otro asesor tomo la conversacion")
        self.conversation = conversation


def list_inbox(
    status: ConversationStatus | None, *, advisor_id: str | None = None, limit: int | None = None
) -> list[Conversation]:
    """Bandeja (RF-032): por estado, o los casos de un asesor si se pasa `advisor_id`.
    Sin filtro: pendientes primero (el que mas espera arriba) y despues en atencion."""
    page = limit or get_settings().inbox_page_size
    if advisor_id:
        return repository.find_conversations_by_advisor(advisor_id, limit=page)
    if status is not None:
        return repository.list_inbox(
            str(status), limit=page, oldest_first=status == ConversationStatus.PENDING_ADVISOR
        )
    pending = repository.list_inbox(str(ConversationStatus.PENDING_ADVISOR), limit=page)
    attending = repository.list_inbox(
        str(ConversationStatus.IN_ATTENTION), limit=page, oldest_first=False
    )
    return (pending + attending)[:page]


def open_thread(
    conversation: Conversation,
    *,
    before: str | None = None,
    after: str | None = None,
    limit: int | None = None,
) -> tuple[list[Message], bool]:
    """El hilo como lo ve el asesor: los ultimos N (RF-033), paginas anteriores con `before`
    (RF-012) o solo lo nuevo con `after` (sondeo). Devuelve `(mensajes, hay_mas_atras)`.
    Abrirlo consume los no leidos (RF-035)."""
    page = limit or get_settings().advisor_thread_page_size
    if after:
        messages = repository.list_messages(conversation.conversation_id, after=after, limit=page)
        has_more = False
    else:
        messages, has_more = repository.list_messages_before(
            conversation.conversation_id, before=before, limit=page
        )
    if conversation.unread_count > 0:
        repository.reset_unread(conversation.conversation_id)
    return messages, has_more


def _system_note(conversation_id: str, event: SystemEvent, metadata: dict) -> Message:
    now = utc_now_iso()
    message_id = str(uuid.uuid4())
    return Message(
        conversation_id=conversation_id,
        message_key=message_key_for(now, message_id),
        message_id=message_id,
        sender_type=SenderType.SYSTEM,
        message_type=MessageType.SYSTEM,
        status=MessageStatus.DELIVERED,
        content=str(event),
        metadata=metadata,
        created_at=now,
    )


def take_conversation(
    conversation: Conversation, *, advisor_id: str, advisor_name: str | None
) -> Conversation:
    """Toma atomica (RF-029 / AC-005). Idempotente si ya es mia; si otro la tiene, error con
    el estado actual para que la app se actualice sin duplicar atencion."""
    if conversation.assigned_advisor_id == advisor_id:
        return conversation
    note = _system_note(
        conversation.conversation_id,
        SystemEvent.ADVISOR_ASSIGNED,
        {"advisor_id": advisor_id, "advisor_name": advisor_name},
    )
    taken = repository.assign_advisor(
        conversation.conversation_id,
        advisor_id,
        allowed_statuses=[str(s) for s in _TAKEABLE_STATUSES],
        note=note,
    )
    current = repository.get_conversation(conversation.conversation_id)
    if current is None:
        raise repository.ConversationNotFound(conversation.conversation_id)
    if not taken:
        raise ConversationAlreadyTaken(current)
    return current


def post_advisor_message(
    conversation: Conversation,
    *,
    advisor_id: str,
    advisor_name: str | None,
    client_message_id: str,
    content: str,
) -> tuple[Message, bool]:
    """Respuesta del asesor (RF-034), idempotente por `client_message_id` (RF-038 / AC-006).
    Nace DELIVERED: persistir es entregar; el widget la recoge en el siguiente sondeo."""
    if conversation.assigned_advisor_id != advisor_id:
        raise NotAssignedToAdvisor(conversation.conversation_id)
    text = content.strip()
    if not text:
        raise EmptyMessage("el mensaje esta vacio")
    limit = get_settings().max_message_chars
    if len(text) > limit:
        raise MessageTooLong(limit)

    now = utc_now_iso()
    message_id = str(uuid.uuid4())
    message = Message(
        conversation_id=conversation.conversation_id,
        message_key=message_key_for(now, message_id),
        message_id=message_id,
        sender_type=SenderType.ADVISOR,
        sender_id=advisor_id,
        message_type=MessageType.TEXT,
        status=MessageStatus.DELIVERED,
        content=text,
        client_message_id=client_message_id,
        # El widget muestra el nombre del asesor (como Intercom firma cada respuesta).
        metadata={"sender_name": advisor_name} if advisor_name else None,
        created_at=now,
    )
    return repository.save_message_idempotent(message, count_as_unread=False)


def close_case(conversation: Conversation, *, advisor_id: str) -> Conversation:
    """Cierre minimo del caso (RF-031 sin ticket, provisional hasta F5)."""
    if conversation.assigned_advisor_id != advisor_id:
        raise NotAssignedToAdvisor(conversation.conversation_id)
    note = _system_note(
        conversation.conversation_id, SystemEvent.TICKET_CLOSED, {"advisor_id": advisor_id}
    )
    if not repository.release_advisor(conversation.conversation_id, advisor_id, note=note):
        raise NotAssignedToAdvisor(conversation.conversation_id)
    current = repository.get_conversation(conversation.conversation_id)
    if current is None:  # pragma: no cover
        raise repository.ConversationNotFound(conversation.conversation_id)
    return current
