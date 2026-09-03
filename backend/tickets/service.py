"""Ciclo de vida del ticket — RF-023, RF-024, RF-031, RF-050. Taxonomía: D-008 (⚠️ abierta).

Un ticket existe **solo cuando hay atención humana** (RF-023): nace con el handoff (D-029) y
muere cuando el asesor cierra el caso. Una conversación que el bot resuelve sola no genera
ninguno.

Su estado va pegado al de la conversación escalada, sin ser el mismo dato:

    conversación PENDING_ADVISOR  →  ticket PENDING
    conversación IN_ATTENTION     →  ticket IN_PROGRESS   (el asesor la tomó)
    conversación CLOSED / al bot  →  ticket CLOSED        (con resolución)

Por qué dos filas y no un campo más en la conversación: la conversación es el hilo que ve el
usuario y la lee el widget en cada sondeo; el ticket es trabajo interno (tipo, prioridad,
datos que faltan, resolución) que solo mira el asesor y cuenta el dashboard. Meterlo todo en
Conversations engordaría el item que se lee más veces por segundo en todo el sistema.

Este módulo puede importar `conversations` (regla de `backend/__init__.py`); `conversations`
NUNCA importa `tickets`. Por eso quien compone "derivar + abrir ticket" es la entrada
(`api/routers/chat.py`), no el dominio.
"""

import uuid

from backend.conversations import repository as conversations_repository
from backend.conversations.models import (
    Conversation,
    ConversationStatus,
    MessageType,
    UserType,
)
from backend.core.clock import utc_now_iso
from backend.tickets import repository
from backend.tickets.models import ClassificationSource, Ticket
from backend.tickets.taxonomy import (
    Category,
    Priority,
    ProblemType,
    Tag,
    TicketStatus,
    missing_data,
    resolve_priority,
    spec_for,
    suggest,
)

# Namespace fijo para derivar el ticket_id de la conversacion escalada (RF-023: 1:1). Cambiarlo
# "perderia" los tickets existentes — mismo patron que _USER_CONVERSATION_NAMESPACE en
# conversations/service.py.
_TICKET_NAMESPACE = uuid.UUID("d4f3a1e0-6b8c-4f2a-9e1d-7c5b0a3f8e12")


def ticket_id_for_conversation(conversation_id: str) -> str:
    """Id determinista del ticket de una conversacion (DETAILS.md §4.4 / Paso 5).

    Antes era aleatorio (`tick_{uuid4()...}`) y la unicidad dependia de consultar el GSI por
    conversation_id antes de crear — eventualmente consistente, asi que dos requests casi
    simultaneos (el handoff real y la red de seguridad `ensure_ticket`) podian pasar los dos el
    "no existe" y crear dos tickets. Con el id derivado, el `attribute_not_exists(ticket_id)`
    de `create_ticket` es la exclusion mutua real: dos intentos calculan el MISMO id y solo uno
    gana la escritura.
    """
    return str(uuid.uuid5(_TICKET_NAMESPACE, f"conversation:{conversation_id}"))


class TicketAlreadyClosed(RuntimeError):
    """El ticket ya está cerrado: no se reabre ni se vuelve a cerrar (se responde 409)."""


def for_conversation(conversation_id: str) -> Ticket | None:
    return repository.find_by_conversation(conversation_id)


def open_ticket(conversation: Conversation, *, description: str | None = None) -> Ticket:
    """Abre el ticket de una conversación recién escalada (RF-023).

    El `problem_type` sale de las reglas sobre el asunto y el detalle del formulario: es una
    **sugerencia** determinista y gratuita (no toca ningún modelo, no gasta la cuota de
    D-027). El asesor la confirma o la corrige, y esa corrección es la medida que necesita
    D-008 antes de cerrarse.

    Idempotente: si la conversación ya tiene ticket, devuelve el que existe. El id determinista
    (`ticket_id_for_conversation`) es lo que hace esa garantía real bajo carrera: dos requests
    casi simultáneos (el handoff y la red de seguridad `ensure_ticket`) calculan el MISMO id, y
    `create_ticket` (condicionado a `attribute_not_exists`) deja pasar solo al primero — sin
    depender de la consistencia eventual del GSI, ni para leer ni para crear.
    """
    ticket_id = ticket_id_for_conversation(conversation.conversation_id)
    existing = repository.get_ticket(ticket_id)
    if existing is not None:
        return existing

    detail = description if description is not None else _form_detail(conversation)
    suggestion = suggest(" ".join(filter(None, (conversation.title, detail))))
    spec = spec_for(suggestion.problem_type)
    tags = [str(tag) for tag in suggestion.tags]
    now = utc_now_iso()
    ticket = Ticket(
        ticket_id=ticket_id,
        conversation_id=conversation.conversation_id,
        user_type=str(conversation.user_type),
        user_id=conversation.user_id,
        user_email=conversation.user_email,
        contact_name=conversation.contact_name,
        contact_email=conversation.contact_email,
        contact_phone=conversation.contact_phone,
        status=TicketStatus.PENDING,
        problem_type=suggestion.problem_type,
        category=spec.category,
        priority=resolve_priority(suggestion.problem_type, tags),
        tags=tags,
        classification_source=ClassificationSource.RULES,
        classification_rule=suggestion.rule,
        title=conversation.title,
        description=detail,
        missing_data=missing_data(suggestion.problem_type, None),
        handoff_reason=conversation.handoff_reason,
        created_at=now,
        updated_at=now,
    )
    if not repository.create_ticket(ticket):
        # Otro request gano la carrera (mismo ticket_id determinista): lectura por PK,
        # fuertemente consistente, no el GSI.
        return repository.get_ticket(ticket_id) or ticket
    return ticket


def ensure_ticket(conversation: Conversation) -> Ticket | None:
    """Red de seguridad: toda conversación escalada tiene ticket, aunque su creación fallara
    en el handoff (la conversación ya era durable y el usuario ya vio la confirmación, así
    que ahí no se puede responder un error).

    Se llama cuando un asesor abre o toma el caso, que es cuando el ticket hace falta de
    verdad. Devuelve None si la conversación no está escalada (el bot la atiende: RF-023, no
    hay trabajo humano que registrar).
    """
    if conversation.status not in (
        ConversationStatus.PENDING_ADVISOR,
        ConversationStatus.IN_ATTENTION,
    ):
        return repository.find_by_conversation(conversation.conversation_id)
    return open_ticket(conversation)


def _form_detail(conversation: Conversation) -> str | None:
    """El detalle que el usuario escribió en el formulario de handoff (D-029), leído del
    mensaje `FORM_RESPONSE` del hilo. Se busca en la ventana reciente porque el formulario es
    de los últimos mensajes del caso: nace con él."""
    for message in reversed(
        conversations_repository.list_recent_messages(conversation.conversation_id, limit=20)
    ):
        if message.message_type == MessageType.FORM_RESPONSE:
            values = (message.metadata or {}).get("form_response", {}).get("values", {})
            return values.get("detail") or message.content
    return None


def list_inbox(
    *, status: TicketStatus | None = None, advisor_id: str | None = None, limit: int = 50
) -> list[Ticket]:
    """Bandeja de tickets (RF-032 aplicado a tickets): por estado, o los de un asesor."""
    if advisor_id:
        mios = repository.find_by_advisor(advisor_id, limit=limit)
        if status is not None:
            return [t for t in mios if t.status == status]
        return [t for t in mios if t.status != TicketStatus.CLOSED]
    return repository.list_inbox(str(status) if status else None, limit=limit)


def assign(conversation: Conversation, *, advisor_id: str) -> Ticket | None:
    """El asesor tomó la conversación (RF-029): su ticket pasa a IN_PROGRESS.

    Se apoya en `ensure_ticket`, así que tomar un caso viejo sin ticket también lo crea. No
    es condicional sobre el asesor: la toma atómica ya la resolvió `conversations` sobre la
    conversación, y el ticket solo refleja lo que allí quedó decidido.
    """
    ticket = ensure_ticket(conversation)
    if ticket is None or ticket.status == TicketStatus.CLOSED:
        return ticket
    now = utc_now_iso()
    changes = {
        "status": str(TicketStatus.IN_PROGRESS),
        "assigned_advisor_id": advisor_id,
        "updated_at": now,
    }
    if ticket.assigned_at is None:
        changes["assigned_at"] = now
    return repository.update_ticket(ticket.ticket_id, changes) or ticket


def reclassify(
    ticket: Ticket,
    *,
    advisor_id: str,
    problem_type: ProblemType | None = None,
    category: Category | None = None,
    priority: Priority | None = None,
    tags: list[str] | None = None,
    collected_data: dict | None = None,
) -> Ticket:
    """El asesor confirma o corrige la clasificación propuesta (D-008 / RF-024).

    Reglas de la actualización:
    - cambiar el `problem_type` arrastra la `category` y los datos mínimos del tipo nuevo,
      salvo que el asesor mande una categoría explícita;
    - la `priority` se recalcula desde tipo + etiquetas (una etiqueta que corre la sube), a
      menos que el asesor la fije a mano: su criterio manda sobre la regla;
    - tocar cualquier cosa marca `classification_source = ADVISOR`, que es lo que separa
      "lo dijo la regla" de "lo confirmó una persona" cuando se evalúe D-008.
    """
    if ticket.status == TicketStatus.CLOSED:
        raise TicketAlreadyClosed(ticket.ticket_id)
    nuevo_tipo = problem_type or ProblemType(ticket.problem_type)
    nuevas_tags = [str(t) for t in tags] if tags is not None else list(ticket.tags)
    datos = {**ticket.collected_data, **(collected_data or {})}
    changes: dict = {
        "problem_type": str(nuevo_tipo),
        "category": str(category or spec_for(nuevo_tipo).category),
        "priority": str(priority or resolve_priority(nuevo_tipo, nuevas_tags)),
        "tags": nuevas_tags,
        "collected_data": datos,
        "missing_data": missing_data(nuevo_tipo, datos),
        "classification_source": str(ClassificationSource.ADVISOR),
        "updated_at": utc_now_iso(),
    }
    updated = repository.update_ticket(ticket.ticket_id, changes)
    if updated is None:  # pragma: no cover — sin condición, solo si desaparece la fila
        raise repository.TicketNotFound(ticket.ticket_id)
    return updated


def close(ticket: Ticket, *, advisor_id: str, resolution: str | None = None) -> Ticket:
    """Cierra el ticket junto con el caso (RF-031). Condicional sobre el estado: si otro
    asesor lo cerró entre la lectura y la escritura, esto no lo vuelve a cerrar."""
    if ticket.status == TicketStatus.CLOSED:
        raise TicketAlreadyClosed(ticket.ticket_id)
    now = utc_now_iso()
    updated = repository.update_ticket(
        ticket.ticket_id,
        {
            "status": str(TicketStatus.CLOSED),
            "resolution": (resolution or "").strip() or None,
            "closed_by": advisor_id,
            "closed_at": now,
            "updated_at": now,
        },
        expected_status=str(ticket.status),
    )
    if updated is None:
        raise TicketAlreadyClosed(ticket.ticket_id)
    return updated


def anonymous(ticket: Ticket) -> bool:
    """El caso lo abrió un visitante: el asesor solo puede ubicarlo por el contacto del
    formulario (RF-003), no por su cuenta VMC."""
    return ticket.user_type == str(UserType.ANONYMOUS)


__all__ = [
    "Tag",
    "TicketAlreadyClosed",
    "anonymous",
    "assign",
    "close",
    "ensure_ticket",
    "for_conversation",
    "list_inbox",
    "open_ticket",
    "reclassify",
]
