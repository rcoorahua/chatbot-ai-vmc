"""Superficie del asesor (KAM/CAM) — `/advisor/*`. RF-012, RF-029, RF-031..RF-036, RF-038.

Contrato con la app del asesor (frontend/):
  GET  /advisor/me                                    → el asesor de este token (auto-alta RF-006)
  GET  /advisor/conversations?status=&mine=&limit=    → bandeja (RF-032): pendientes primero
  GET  /advisor/conversations/{id}                    → conversacion + contexto del usuario
  GET  /advisor/conversations/{id}/messages           → ultimos N (RF-033); `before=` pagina hacia
                                                        atras (RF-012); `after=` solo lo nuevo.
                                                        Abrirlo consume los no leidos (RF-035)
  POST /advisor/conversations/{id}/take               → toma atomica (RF-029 / AC-005); 409 si
                                                        otro la tiene (con el estado actual) o si
                                                        es de un visitante (D-031: solo el bot)
  POST /advisor/conversations/{id}/messages           → 201, idempotente por client_message_id
                                                        (RF-034 / RF-038 / AC-006); 409 si no es mia
  POST /advisor/conversations/{id}/close              → cierre (RF-031): un caso queda CLOSED
                                                        (D-029); un hilo con el bot vuelve al bot
                                                        (D-023). Cierra tambien el ticket, con
                                                        `resolution` opcional
  GET  /advisor/taxonomy                              → tipos de problema, categorias, prioridades y
                                                        etiquetas (⚠️ propuesta: D-008 abierta)
  GET  /advisor/tickets?status=&mine=&limit=          → bandeja de tickets (RF-023)
  GET  /advisor/conversations/{id}/ticket             → el ticket del caso; lo crea si faltaba
  PATCH /advisor/tickets/{ticket_id}                  → confirmar o corregir la clasificacion y
                                                        registrar los datos minimos (RF-024)

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
from backend.api.schemas import (
    AdvisorOut,
    ConversationDetail,
    MessageAccepted,
    MessageOut,
    TicketOut,
    page_cursors,
)
from backend.conversations import service
from backend.conversations.models import Conversation, ConversationStatus
from backend.core import auth
from backend.tickets import service as tickets
from backend.tickets import taxonomy

router = APIRouter(prefix="/advisor", tags=["advisor"])


# ───────────────────────────────────── Dependencias ─────────────────────────────────────


def get_current_advisor(claims: auth.CurrentClaims) -> Advisor:
    return advisors.resolve_advisor(claims)  # DISABLED → 403 en api/errors.py


CurrentAdvisor = Annotated[Advisor, Depends(get_current_advisor)]


def _load(conversation_id: str) -> Conversation:
    conversation = service.get_conversation(conversation_id)
    if conversation is None:
        raise service.ConversationNotFound(conversation_id)  # 404 en api/errors.py
    return conversation


# ───────────────────────────────── Modelos de entrada/salida ─────────────────────────────────


class InboxOut(BaseModel):
    conversations: list[ConversationDetail]


class TicketsOut(BaseModel):
    tickets: list[TicketOut]


class TicketPatch(BaseModel):
    """Lo que el asesor puede cambiar de un ticket. Todo opcional: se aplica solo lo enviado.

    No incluye `status` a proposito — el estado lo mueven `take` y `close` sobre la
    conversacion, para que el ticket no pueda quedar en un estado que el hilo contradiga.
    """

    problem_type: taxonomy.ProblemType | None = None
    category: taxonomy.Category | None = None
    priority: taxonomy.Priority | None = None
    tags: list[taxonomy.Tag] | None = None
    collected_data: dict[str, Any] | None = None


class CloseIn(BaseModel):
    """Cuerpo OPCIONAL del cierre: como se resolvio, para el registro del ticket (RF-050)."""

    resolution: str | None = Field(default=None, max_length=2_000)


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


class ConflictDetail(BaseModel):
    detail: str
    conversation: dict[str, Any]


# ──────────────────────────────────────── Rutas ────────────────────────────────────────


@router.get("/me", response_model=AdvisorOut)
def me(advisor: CurrentAdvisor) -> AdvisorOut:
    return AdvisorOut.from_model(advisor)


@router.get("/taxonomy")
def get_taxonomy(advisor: CurrentAdvisor) -> dict:
    """Tipos de problema, categorias, prioridades y etiquetas (`tickets/taxonomy.py`).

    ⚠️ `proposal: true`: D-008 sigue ABIERTA (Silvana + Julio). La app la dibuja como
    provisional; leerla de aqui evita que la lista quede copiada en el frontend.
    """
    return taxonomy.as_catalog()


@router.get("/tickets", response_model=TicketsOut)
def ticket_inbox(
    advisor: CurrentAdvisor,
    status_filter: taxonomy.TicketStatus | None = Query(default=None, alias="status"),
    mine: bool = Query(default=False, description="Solo los tickets asignados a mi"),
    limit: int = Query(default=50, ge=1, le=100),
) -> TicketsOut:
    found = tickets.list_inbox(
        status=status_filter,
        advisor_id=advisor.advisor_id if mine else None,
        limit=limit,
    )
    return TicketsOut(tickets=[TicketOut.from_model(t) for t in found])


@router.get("/conversations/{conversation_id}/ticket", response_model=TicketOut)
def get_ticket(conversation_id: str, advisor: CurrentAdvisor) -> TicketOut:
    """El ticket del caso. Si la conversacion esta escalada y no lo tenia (fallo al derivar),
    se crea aqui: ningun caso llega al asesor sin registro. 404 si el bot la atiende, porque
    ahi no hay trabajo humano que registrar (RF-023)."""
    ticket = tickets.ensure_ticket(_load(conversation_id))
    if ticket is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Esta conversacion no tiene ticket: la atiende el bot"
        )
    return TicketOut.from_model(ticket)


@router.patch("/tickets/{ticket_id}", response_model=TicketOut)
def patch_ticket(ticket_id: str, body: TicketPatch, advisor: CurrentAdvisor) -> TicketOut:
    """Confirmar o corregir la clasificacion propuesta y registrar los datos minimos que el
    asesor ya obtuvo (RF-024). Un ticket cerrado no se edita (409)."""
    ticket = tickets.get_ticket(ticket_id)
    if ticket is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ticket no encontrado")
    updated = tickets.reclassify(  # cerrado → 409 en api/errors.py
        ticket,
        advisor_id=advisor.advisor_id,
        problem_type=body.problem_type,
        category=body.category,
        priority=body.priority,
        tags=[str(t) for t in body.tags] if body.tags is not None else None,
        collected_data=body.collected_data,
    )
    return TicketOut.from_model(updated)


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
    conversation, messages, has_more = service.open_thread(
        _load(conversation_id), before=before, after=after, limit=limit
    )
    next_before, next_after = page_cursors(messages, before=before, after=after)
    return ThreadOut(
        conversation=ConversationDetail.from_model(conversation),
        messages=[MessageOut.from_model(m) for m in messages],
        next_before=next_before,
        has_more=has_more,
        next_after=next_after,
    )


@router.post(
    "/conversations/{conversation_id}/take",
    response_model=ConversationDetail,
    responses={409: {"model": ConflictDetail}},
)
def take(conversation_id: str, advisor: CurrentAdvisor) -> ConversationDetail:
    # 409 con el estado actual si otro la tiene o si es de un visitante (api/errors.py,
    # AC-005: el que pierde se actualiza sin duplicar atencion).
    taken = service.take_conversation(
        _load(conversation_id), advisor_id=advisor.advisor_id, advisor_name=advisor.name
    )
    # El ticket sigue a la conversacion: tomarla lo pasa a IN_PROGRESS (y lo crea si el caso
    # venia sin uno). Nunca al reves: la toma atomica se decide sobre la conversacion.
    tickets.assign(taken, advisor_id=advisor.advisor_id)
    return ConversationDetail.from_model(taken)


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=MessageAccepted,
    status_code=status.HTTP_201_CREATED,
)
def post_message(
    conversation_id: str, body: AdvisorMessageIn, advisor: CurrentAdvisor
) -> MessageAccepted:
    # 409 si no es mia o esta cerrada, 422 si esta vacio o es muy largo (api/errors.py).
    message, created = service.post_advisor_message(
        _load(conversation_id),
        advisor_id=advisor.advisor_id,
        advisor_name=advisor.name,
        client_message_id=body.client_message_id,
        content=body.content,
    )
    return MessageAccepted(message=MessageOut.from_model(message), duplicate=not created)


@router.post("/conversations/{conversation_id}/close", response_model=ConversationDetail)
def close(
    conversation_id: str, advisor: CurrentAdvisor, body: CloseIn | None = None
) -> ConversationDetail:
    # 409 si no es el asesor asignado o si ya estaba cerrado (api/errors.py).
    closed = service.close_case(_load(conversation_id), advisor_id=advisor.advisor_id)
    # El ticket se cierra con el caso (RF-031). Si ya estaba cerrado no es un error: la
    # conversacion es la fuente de verdad del cierre y este endpoint es idempotente para ella.
    ticket = tickets.for_conversation(conversation_id)
    if ticket is not None:
        try:
            tickets.close(
                ticket,
                advisor_id=advisor.advisor_id,
                resolution=body.resolution if body else None,
            )
        except tickets.TicketAlreadyClosed:
            pass
    return ConversationDetail.from_model(closed)
