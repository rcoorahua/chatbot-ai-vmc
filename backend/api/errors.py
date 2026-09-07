"""Excepciones de dominio → respuestas HTTP, en UN solo lugar.

Cada excepcion del dominio (`conversations.service`, `tickets.service`, `advisors.service`,
`core.auth`, `conversations.forms`) tiene aqui su codigo y su mensaje. Los routers llaman al
servicio y dejan que la excepcion suba: antes cada endpoint repetia el `try/except` (17
clausulas en dos routers, con mensajes distintos para la misma excepcion; auditoria
2026-09-06). El log `http.error` (request_log) sigue saliendo igual: el manejador construye
la `HTTPException` y se la pasa al mismo `log_http_exception`.

Regla: una excepcion que carga datos (`limit`, `retry_after`, `field`, `conversation`) los
expone en la respuesta; el texto es para la persona (español, RF-052: sin contenido ajeno).
"""

from collections.abc import Callable

from fastapi import FastAPI, HTTPException, Request, status

from backend.advisors import service as advisors
from backend.api import request_log
from backend.api.schemas import ConversationDetail
from backend.conversations import forms, service
from backend.conversations.models import Conversation
from backend.core import auth
from backend.tickets import service as tickets

Responder = Callable[[Exception], HTTPException]


def _conflict_with_state(message: str, conversation: Conversation) -> HTTPException:
    """409 que ademas trae el estado ACTUAL de la conversacion (AC-005): el que pierde la
    toma se actualiza sin duplicar atencion."""
    return HTTPException(
        status.HTTP_409_CONFLICT,
        {
            "detail": message,
            "conversation": ConversationDetail.from_model(conversation).model_dump(),
        },
    )


RESPONDERS: dict[type[Exception], Responder] = {
    # ── identidad y configuracion ──
    # Un JWT invalido NO degrada a anonimo en silencio: el widget debe enterarse de que la
    # identidad no paso, porque un usuario logueado tratado como anonimo perderia su
    # historial sin explicacion.
    auth.IdentityError: lambda exc: HTTPException(
        status.HTTP_401_UNAUTHORIZED, f"Identidad VMC invalida: {exc}"
    ),
    auth.IdentityConfigurationError: lambda exc: HTTPException(
        status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)
    ),
    advisors.AdvisorDisabled: lambda exc: HTTPException(
        status.HTTP_403_FORBIDDEN, "Asesor deshabilitado"
    ),
    # ── conversaciones y mensajes ──
    service.ConversationNotFound: lambda exc: HTTPException(
        status.HTTP_404_NOT_FOUND, "Conversacion no encontrada"
    ),
    service.ConversationClosed: lambda exc: HTTPException(
        status.HTTP_409_CONFLICT, "Esta conversacion ya esta cerrada: es de solo lectura."
    ),
    service.EmptyMessage: lambda exc: HTTPException(422, str(exc)),
    service.MessageTooLong: lambda exc: HTTPException(422, str(exc)),
    # `Retry-After` es el estandar de 429: el widget lo respeta en vez de reintentar solo.
    service.RateLimited: lambda exc: HTTPException(
        status.HTTP_429_TOO_MANY_REQUESTS,
        "Estas enviando mensajes muy rapido. Espera un momento.",
        headers={"Retry-After": str(exc.retry_after)},
    ),
    # ── handoff (D-029 / D-031) ──
    forms.FormValidationError: lambda exc: HTTPException(
        422, {"detail": str(exc), "field": exc.field}
    ),
    service.HandoffNotAllowed: lambda exc: HTTPException(
        status.HTTP_409_CONFLICT, "Desde esta conversacion no se puede pedir un asesor"
    ),
    service.TooManyOpenCases: lambda exc: HTTPException(
        status.HTTP_409_CONFLICT,
        f"Ya tienes {exc.limit} casos abiertos. Continua en uno de ellos o espera a que un "
        "asesor lo cierre.",
    ),
    # ── asesor ──
    service.NotAssignedToAdvisor: lambda exc: HTTPException(
        status.HTTP_409_CONFLICT, "Esta conversacion no esta asignada a ti: primero tomala."
    ),
    service.ConversationAlreadyTaken: lambda exc: _conflict_with_state(
        "La conversacion ya esta tomada o no se puede tomar en su estado", exc.conversation
    ),
    service.AnonymousConversation: lambda exc: _conflict_with_state(
        "Las conversaciones de visitantes las atiende solo el bot (D-031)", exc.conversation
    ),
    tickets.TicketAlreadyClosed: lambda exc: HTTPException(
        status.HTTP_409_CONFLICT, "El ticket esta cerrado y ya no se puede editar"
    ),
}


def _handler(responder: Responder):
    async def handle(request: Request, exc: Exception):
        return await request_log.log_http_exception(request, responder(exc))

    return handle


def install(app: FastAPI) -> None:
    """Registra un manejador por excepcion de dominio. Se llama una vez, en `api/main.py`."""
    for exception_class, responder in RESPONDERS.items():
        app.add_exception_handler(exception_class, _handler(responder))
