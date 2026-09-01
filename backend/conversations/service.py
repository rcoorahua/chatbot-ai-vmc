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
from backend.core.clock import minutes_ago_iso, utc_now_iso
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


class RateLimited(RuntimeError):
    """Demasiados mensajes en la ventana (RF-014 / D-005). Se responde 429."""

    def __init__(self, limit: int, retry_after: int) -> None:
        super().__init__(f"maximo {limit} mensajes por minuto")
        self.limit = limit
        self.retry_after = retry_after


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
    metadata: dict | None = None,
) -> tuple[Message, bool]:
    """Persiste el mensaje del usuario. `(mensaje, True)` si es nuevo; `(original, False)` si
    es un reintento con el mismo `client_message_id` (RF-038)."""
    settings = get_settings()
    text = content.strip()
    if not text:
        raise EmptyMessage("el mensaje esta vacio")
    if len(text) > settings.max_message_chars:
        raise MessageTooLong(settings.max_message_chars)
    _check_rate_limit(conversation.conversation_id)

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
        # El evento estructurado de un quick reply (D-028) viaja aqui; el worker lo valida
        # contra el paso vigente del flujo — nunca se confia en el cliente (security-guidance).
        metadata=metadata,
        created_at=now,
    )
    # Solo cuenta como "no leido" para el asesor si el bot ya no atiende (RF-035): mientras la
    # IA responde sola, no hay nadie que deba leerlo.
    return repository.save_message_idempotent(
        message, count_as_unread=not conversation.bot_enabled
    )


def _check_rate_limit(conversation_id: str) -> None:
    """RF-014 / D-005: tope de mensajes por minuto y por conversacion (= por usuario, D-002).

    Frena la rafaga sin castigar al que escribe rapido en frases partidas. Se cuenta solo lo
    que manda el usuario: las respuestas del bot y del asesor no consumen su cuota.
    """
    limit = get_settings().max_messages_per_minute
    if limit <= 0:  # 0 o negativo = sin limite (util en pruebas y en un incidente)
        return
    recientes = repository.count_messages_since(
        conversation_id, since=minutes_ago_iso(1), sender_type=str(SenderType.USER)
    )
    if recientes >= limit:
        raise RateLimited(limit, retry_after=60)


def list_messages(
    conversation_id: str, *, after: str | None = None, limit: int | None = None
) -> list[Message]:
    page = limit or get_settings().messages_page_size
    return repository.list_messages(conversation_id, after=after, limit=page)


def context_window(conversation_id: str) -> list[Message]:
    """La memoria del bot (RF-013 / D-004, cerrada 2026-08-28): los ultimos N mensajes de la
    ultima hora, en orden cronologico.

    NO hay resumen acumulado: los campos `summary`/`summary_updated_at` de Conversations
    quedan sin uso a proposito. Con D-003 la conversacion del autenticado no se cierra nunca,
    asi que sin corte temporal el bot arrastraria contexto de semanas atras — caro y confuso.
    Si el usuario vuelve pasada la hora, la lista sale vacia (o solo con su mensaje nuevo) y la
    IA responde a la pregunta actual, que es lo que espera quien retoma despues de un rato.
    """
    settings = get_settings()
    return repository.list_recent_messages(
        conversation_id,
        limit=settings.ai_context_messages,
        since=minutes_ago_iso(settings.ai_context_window_minutes),
    )


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


# ───────────────────────────── Lado del bot (RF-020..027, worker IA) ─────────────────────────────


def post_bot_message(
    conversation_id: str, text: str, *, metadata: dict | None = None
) -> Message:
    """Respuesta del bot en el hilo. Nace DELIVERED (persistir es entregar; el widget la
    recoge en el sondeo) y no cuenta como no leida: los no leidos son del asesor (RF-035)."""
    now = utc_now_iso()
    message_id = str(uuid.uuid4())
    message = Message(
        conversation_id=conversation_id,
        message_key=message_key_for(now, message_id),
        message_id=message_id,
        sender_type=SenderType.BOT,
        message_type=MessageType.TEXT,
        status=MessageStatus.DELIVERED,
        content=text,
        metadata=metadata,
        created_at=now,
    )
    repository.put_message(message, count_as_unread=False)
    return message


def start_handoff(conversation: Conversation, *, reason: str) -> bool:
    """Deriva a asesor (RF-022): PENDING_ADVISOR, bot apagado (RF-025) y nota SYSTEM
    `HANDOFF_REQUESTED` en el hilo. Devuelve False si ya estaba derivada o asignada.

    La IA queda apagada hasta que un asesor TOME y CIERRE el caso (D-023 la devuelve al bot).
    Es D-007, cerrada el 2026-08-28 (Aaron): no se re-enciende sola, sin expiracion ni
    temporizador — si nadie lo atiende, sigue esperando.
    Solo autenticados: el anonimo no deriva (D-002); eso lo decide el worker antes de llamar.
    """
    note = _system_note(
        conversation.conversation_id, SystemEvent.HANDOFF_REQUESTED, {"reason": reason}
    )
    return repository.start_handoff(
        conversation.conversation_id, reason=reason, at=note.created_at, note=note
    )


def send_wait_message_once(conversation: Conversation, text: str) -> bool:
    """RF-027 / AC-004: si el usuario insiste mientras espera asesor, el aviso fijo sale UNA
    sola vez por periodo pendiente. El flag se gana con un update condicional, asi que dos
    jobs concurrentes no lo duplican. Devuelve True si este llamador lo envio."""
    if conversation.wait_message_sent:
        return False
    if not repository.mark_wait_message_sent(conversation.conversation_id):
        return False
    post_bot_message(conversation.conversation_id, text)
    return True


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
