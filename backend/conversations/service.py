"""Orquestacion del dominio conversacion (SIN llamar integraciones — regla de backend/__init__.py).

Reglas de negocio (CLAUDE.md; D-029 cerrada el 2026-09-02 revisa D-002/D-003/D-017/D-019):
- Autenticado: UN hilo permanente con el bot (kind=THREAD, id determinista, D-003) y hasta N
  CASOS abiertos (kind=CASE) que nacen del formulario de handoff. Escalar no apaga el hilo:
  el caso espera al asesor aparte y el bot sigue respondiendo en el hilo.
- Anonimo: UNA conversacion por sesion (D-002/D-018), sin cuenta no se recupera (RF-004).
  Puede pedir asesor dejando nombre y correo en el formulario (RF-003): la derivacion es en
  el sitio (esa conversacion pasa a PENDING_ADVISOR) y caduca por TTL.
- CLOSED es definitivo y de solo lectura (caso o conversacion anonima); el hilo del
  autenticado nunca se cierra: si un asesor lo tomo y lo cierra, vuelve al bot (D-023).
- RF-014: el largo del mensaje se limita por configuracion (D-005).

Lo que NO hace: encolar el job de IA. Eso lo compone la entrada (api/routers/chat.py) con
core/jobs.py, para que el dominio no dependa de SQS.
"""

import uuid
from datetime import timedelta

from backend.conversations import forms, repository
from backend.conversations.models import (
    ClosedBy,
    Conversation,
    ConversationKind,
    ConversationStatus,
    Message,
    MessageStatus,
    MessageType,
    SenderType,
    SystemEvent,
    UserType,
    message_key_for,
)
from backend.core.auth import ChatSession, VmcIdentity
from backend.core.clock import epoch_seconds, minutes_ago_iso, to_iso, utc_now, utc_now_iso
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


class ConversationClosed(RuntimeError):
    """La conversacion esta CLOSED: es de solo lectura (D-029). Se responde 409."""


class HandoffNotAllowed(RuntimeError):
    """Solo se deriva desde el hilo del bot mientras el bot atiende y nadie lo tomo."""


class TooManyOpenCases(RuntimeError):
    """El usuario ya tiene el maximo de casos abiertos (D-029). Se responde 409."""

    def __init__(self, limit: int) -> None:
        super().__init__(f"ya tienes {limit} casos abiertos")
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
            # D-029: sin cuenta no hay forma de volver; la fila y sus mensajes caducan solos.
            expires_at=_anonymous_ttl(),
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


def _anonymous_ttl() -> int | None:
    days = get_settings().anonymous_conversation_ttl_days
    return epoch_seconds() + days * 86400 if days > 0 else None


def owns(session: ChatSession, conversation: Conversation) -> bool:
    """Autorizacion del chat publico (RNF-005). Autenticado: todo lo suyo (hilo y casos) por
    `user_id`; anonimo: solo la conversacion atada a su token."""
    if session.is_authenticated:
        return bool(session.user_id) and conversation.user_id == session.user_id
    return conversation.conversation_id == session.conversation_id


def list_conversations(session: ChatSession) -> list[Conversation]:
    """Lo que el widget lista en "Mensajes" (D-029): el hilo del bot primero y despues los
    casos, el mas reciente arriba. El anonimo solo tiene su conversacion."""
    if not session.is_authenticated or not session.user_id:
        current = repository.get_conversation(session.conversation_id)
        return [current] if current else []
    found = repository.find_conversations_by_user(
        session.user_id, limit=get_settings().inbox_page_size
    )
    threads = [c for c in found if c.kind == ConversationKind.THREAD]
    if not threads:
        # Un usuario con mas casos que la pagina: el hilo se rescata por su id conocido.
        thread = repository.get_conversation(session.conversation_id)
        threads = [thread] if thread else []
    cases = sorted(
        (c for c in found if c.kind == ConversationKind.CASE),
        key=lambda c: c.last_message_at,
        reverse=True,
    )
    return threads + cases


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
    if conversation.status == ConversationStatus.CLOSED:
        raise ConversationClosed(conversation.conversation_id)
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
        expires_at=conversation.expires_at,
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


def latest_messages(
    conversation_id: str, *, before: str | None = None, limit: int | None = None
) -> tuple[list[Message], bool]:
    """Los ultimos N del hilo, o la pagina anterior a `before` (widget, D-029): la
    conversacion del autenticado es permanente y arrancar por los mas antiguos mostraria el
    principio de hace meses en vez de lo ultimo. Devuelve `(mensajes, hay_mas_atras)`."""
    page = limit or get_settings().messages_page_size
    return repository.list_messages_before(conversation_id, before=before, limit=page)


# ───────────────────────────── Handoff con formulario (D-029) ─────────────────────────────


def request_handoff(
    conversation: Conversation, form: forms.HandoffForm, *, confirmation: str
) -> Conversation:
    """El usuario envio el formulario de handoff (RF-022 / RF-024; RF-003 para el anonimo).

    Anonimo: su unica conversacion se deriva en el sitio (PENDING_ADVISOR, bot apagado) con
    el asunto y el contacto guardados en la fila. Autenticado: se abre un CASO nuevo con el
    formulario y una transcripcion del hilo; el hilo sigue con el bot encendido.
    `confirmation` es el texto fijo del bot (lo trae la entrada: el dominio no importa
    prompts). Devuelve la conversacion que espera al asesor (la misma o el caso).
    """
    if (
        conversation.kind != ConversationKind.THREAD
        or conversation.status != ConversationStatus.BOT_ATTENDING
        or conversation.assigned_advisor_id
    ):
        raise HandoffNotAllowed(conversation.conversation_id)
    anonymous = conversation.user_type == UserType.ANONYMOUS
    needs_email = not anonymous and not conversation.user_email
    clean = forms.validate_handoff_form(
        form,
        anonymous=anonymous,
        needs_email=needs_email,
        max_detail_chars=get_settings().max_message_chars,
    )
    if anonymous:
        return _handoff_in_place(conversation, clean, confirmation=confirmation)
    return _open_case(conversation, clean, confirmation=confirmation)


def _handoff_in_place(
    conversation: Conversation, clean: forms.HandoffForm, *, confirmation: str
) -> Conversation:
    t0, t1, t2 = _stamps(3)
    ttl = conversation.expires_at
    response = _form_response_message(conversation.conversation_id, clean, created_at=t0,
                                      transcript=None, expires_at=ttl)
    # Cuenta como no leido: desde aqui quien lee es el asesor (RF-035).
    repository.put_message(response, count_as_unread=True)
    note = _system_note(conversation.conversation_id, SystemEvent.HANDOFF_REQUESTED,
                        {"reason": "user_form"}, created_at=t1, expires_at=ttl)
    started = repository.start_handoff(
        conversation.conversation_id,
        reason="user_form",
        at=t1,
        note=note,
        title=clean.subject,
        contact={
            "contact_name": clean.name or "",
            "contact_email": clean.email or "",
            "contact_phone": clean.phone or "",
        },
    )
    if not started:
        raise HandoffNotAllowed(conversation.conversation_id)
    post_bot_message(conversation.conversation_id, confirmation, created_at=t2, expires_at=ttl)
    current = repository.get_conversation(conversation.conversation_id)
    if current is None:  # pragma: no cover
        raise repository.ConversationNotFound(conversation.conversation_id)
    return current


def _open_case(
    thread: Conversation, clean: forms.HandoffForm, *, confirmation: str
) -> Conversation:
    limit = get_settings().max_open_cases_per_user
    if limit > 0 and thread.user_id and len(repository.list_open_cases(thread.user_id)) >= limit:
        raise TooManyOpenCases(limit)
    t0, t1, t2, t3 = _stamps(4)
    case_id = str(uuid.uuid4())
    opened = _system_note(case_id, SystemEvent.CASE_OPENED,
                          {"source_conversation_id": thread.conversation_id}, created_at=t0)
    response = _form_response_message(case_id, clean, created_at=t1,
                                      transcript=_transcript(thread), expires_at=None)
    confirm = _bot_message(case_id, confirmation, created_at=t2)
    case = Conversation(
        conversation_id=case_id,
        user_type=UserType.AUTHENTICATED,
        kind=ConversationKind.CASE,
        status=ConversationStatus.PENDING_ADVISOR,
        bot_enabled=False,
        user_id=thread.user_id,
        user_name=thread.user_name,
        user_email=thread.user_email or clean.email,
        user_company=thread.user_company,
        title=clean.subject,
        contact_email=clean.email,
        source_conversation_id=thread.conversation_id,
        message_count=3,
        unread_count=1,
        last_message_preview=(confirm.content or "")[:120],
        last_message_at=t2,
        handoff_requested_at=t1,
        handoff_reason="user_form",
        created_at=t0,
        updated_at=t2,
    )
    if not repository.create_conversation_with_messages(case, [opened, response, confirm]):
        raise RuntimeError("colision de id al crear el caso")  # pragma: no cover
    # Nota en el hilo de origen: enlaza al caso; el bot sigue encendido ahi.
    link = _system_note(thread.conversation_id, SystemEvent.CASE_OPENED,
                        {"case_id": case_id, "title": clean.subject}, created_at=t3)
    repository.put_message(link, count_as_unread=False)
    return case


def _transcript(thread: Conversation) -> list[dict]:
    """Los ultimos mensajes del hilo, para que el asesor tenga el contexto sin abrir otro
    hilo. Solo texto de USER/BOT/ADVISOR, recortado: es contexto, no el historial."""
    recent = repository.list_recent_messages(
        thread.conversation_id, limit=get_settings().ai_context_messages
    )
    return [
        {"sender_type": str(m.sender_type), "content": m.content[:300], "created_at": m.created_at}
        for m in recent
        if m.content and m.sender_type != SenderType.SYSTEM
    ]


def _form_response_message(
    conversation_id: str,
    clean: forms.HandoffForm,
    *,
    created_at: str,
    transcript: list[dict] | None,
    expires_at: int | None,
) -> Message:
    message_id = str(uuid.uuid4())
    values = {
        k: v
        for k, v in (("subject", clean.subject), ("detail", clean.detail), ("name", clean.name),
                     ("email", clean.email), ("phone", clean.phone))
        if v
    }
    metadata: dict = {
        "form_response": {
            "form": forms.HANDOFF_FORM,
            "version": forms.HANDOFF_FORM_VERSION,
            "values": values,
        }
    }
    if transcript:
        metadata["transcript"] = transcript
    return Message(
        conversation_id=conversation_id,
        message_key=message_key_for(created_at, message_id),
        message_id=message_id,
        sender_type=SenderType.USER,
        message_type=MessageType.FORM_RESPONSE,
        # No pasa por el worker (no hay nada que la IA deba hacer): nace atendido.
        status=MessageStatus.PROCESSED,
        content=forms.summary_text(clean),
        metadata=metadata,
        created_at=created_at,
        expires_at=expires_at,
    )


def _stamps(count: int) -> list[str]:
    """`count` timestamps estrictamente crecientes (1 ms entre si): varios mensajes escritos
    en la misma operacion necesitan SKs distintas y en el orden en que se leen."""
    base = utc_now()
    return [to_iso(base + timedelta(milliseconds=i)) for i in range(count)]


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
        # Los cerrados conservan `assigned_advisor_id` como historial: fuera de la bandeja.
        mine = repository.find_conversations_by_advisor(advisor_id, limit=page)
        return [c for c in mine if c.status != ConversationStatus.CLOSED]
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


def _system_note(
    conversation_id: str,
    event: SystemEvent,
    metadata: dict,
    *,
    created_at: str | None = None,
    expires_at: int | None = None,
) -> Message:
    now = created_at or utc_now_iso()
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
        expires_at=expires_at,
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


def _bot_message(
    conversation_id: str,
    text: str,
    *,
    metadata: dict | None = None,
    created_at: str | None = None,
    expires_at: int | None = None,
) -> Message:
    now = created_at or utc_now_iso()
    message_id = str(uuid.uuid4())
    return Message(
        conversation_id=conversation_id,
        message_key=message_key_for(now, message_id),
        message_id=message_id,
        sender_type=SenderType.BOT,
        message_type=MessageType.TEXT,
        status=MessageStatus.DELIVERED,
        content=text,
        metadata=metadata,
        created_at=now,
        expires_at=expires_at,
    )


def post_bot_message(
    conversation_id: str,
    text: str,
    *,
    metadata: dict | None = None,
    created_at: str | None = None,
    expires_at: int | None = None,
) -> Message:
    """Respuesta del bot en el hilo. Nace DELIVERED (persistir es entregar; el widget la
    recoge en el sondeo) y no cuenta como no leida: los no leidos son del asesor (RF-035).
    `expires_at` acompaña al TTL de la conversacion anonima (D-029)."""
    message = _bot_message(
        conversation_id, text, metadata=metadata, created_at=created_at, expires_at=expires_at
    )
    repository.put_message(message, count_as_unread=False)
    return message


def start_handoff(conversation: Conversation, *, reason: str) -> bool:
    """Deriva a asesor sin formulario (RF-022): PENDING_ADVISOR, bot apagado (RF-025) y nota
    SYSTEM `HANDOFF_REQUESTED` en el hilo. Devuelve False si ya estaba derivada o asignada.

    Con D-029 el camino normal es `request_handoff` (formulario); esto queda para reglas o
    herramientas que deriven sin pedir datos. La IA queda apagada hasta que un asesor TOME y
    CIERRE (D-007: no se re-enciende sola, sin expiracion ni temporizador).
    """
    note = _system_note(
        conversation.conversation_id, SystemEvent.HANDOFF_REQUESTED, {"reason": reason},
        expires_at=conversation.expires_at,
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
    post_bot_message(conversation.conversation_id, text, expires_at=conversation.expires_at)
    return True


def returns_to_bot_on_close(conversation: Conversation) -> bool:
    """El hilo permanente del autenticado no se cierra (D-003): cerrarlo lo devuelve al bot.
    Un caso o la conversacion anonima si terminan CLOSED (D-029)."""
    return (
        conversation.kind == ConversationKind.THREAD
        and conversation.user_type == UserType.AUTHENTICATED
    )


def close_case(conversation: Conversation, *, advisor_id: str) -> Conversation:
    """Cierre por el asesor (RF-031). Dos destinos segun `returns_to_bot_on_close`:
    - hilo del autenticado: nota TICKET_CLOSED y vuelve a BOT_ATTENDING con el bot encendido;
    - caso o conversacion anonima: nota CONVERSATION_CLOSED y queda CLOSED, solo lectura.
    Solo el asesor asignado cierra."""
    if conversation.assigned_advisor_id != advisor_id:
        raise NotAssignedToAdvisor(conversation.conversation_id)
    if returns_to_bot_on_close(conversation):
        note = _system_note(
            conversation.conversation_id, SystemEvent.TICKET_CLOSED, {"advisor_id": advisor_id}
        )
        done = repository.release_advisor(conversation.conversation_id, advisor_id, note=note)
    else:
        note = _system_note(
            conversation.conversation_id, SystemEvent.CONVERSATION_CLOSED,
            {"advisor_id": advisor_id}, expires_at=conversation.expires_at,
        )
        done = repository.close_conversation(
            conversation.conversation_id, advisor_id, note=note, closed_by=str(ClosedBy.ADVISOR)
        )
    if not done:
        raise NotAssignedToAdvisor(conversation.conversation_id)
    current = repository.get_conversation(conversation.conversation_id)
    if current is None:  # pragma: no cover
        raise repository.ConversationNotFound(conversation.conversation_id)
    return current
