"""Log de peticiones HTTP (RNF-006) — qué ruta se llamó, con qué resultado y en cuánto.

Hasta ahora la observabilidad cubría el pipeline de IA (`ai.execution`, `ai.rag`, `ai.handoff`)
pero no las peticiones: un 404 o un 403 no dejaban ni una línea, así que "¿por qué el widget no
carga el hilo?" había que reproducirlo a mano. Esto lo cierra con dos piezas:

- `RequestLogMiddleware` emite un `http.request` por petición (método, ruta, estado, duración);
- el manejador de `HTTPException` emite un `http.error` con el **detalle** del rechazo, que es
  lo que explica el 404 ("Conversacion no encontrada") o el 409 ("Primero toma la conversacion").

Nivel según el resultado, para que en prod (INFO, sin contenido) los problemas salten solos:
2xx/3xx → DEBUG, 4xx → WARNING, 5xx → ERROR. En dev/stage el DEBUG está encendido y se ve todo.

Qué NO se registra, a propósito:
- **el cuerpo de la petición ni el de la respuesta**: ahí viajan los mensajes del usuario y los
  datos del formulario de handoff (nombre, correo, teléfono). La política de RNF-006 es que el
  contenido solo aparece vía `content_preview`, y en prod ni eso;
- **la cabecera `Authorization`**: lleva el token de sesión, que es una credencial;
- **la query string cruda**: hoy solo trae cursores y límites, pero es el sitio donde un
  parámetro nuevo con datos personales se colaría sin que nadie lo note.

La `route` es la PLANTILLA (`/chat/conversations/{conversation_id}/messages`), no el path con
el id dentro: es lo que permite agrupar y contar por endpoint en CloudWatch. El `path` real
también va, porque para depurar hace falta saber a qué conversación se refería.
"""

import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

logger = logging.getLogger(__name__)

# Rutas que no se registran: el sondeo del widget golpea `/health` desde el load balancer y
# `OPTIONS` es el preflight de CORS. Registrarlas ahogaría el log de lo que sí importa.
_SILENT_PATHS = frozenset({"/health"})


def _level_for(status: int) -> int:
    if status >= 500:
        return logging.ERROR
    if status >= 400:
        return logging.WARNING
    return logging.DEBUG


def _route_template(request: Request) -> str:
    """La plantilla de la ruta que atendió (`/chat/conversations/{id}`), o el path si no hubo
    coincidencia — que es justamente el caso de un 404 por ruta inexistente."""
    route = request.scope.get("route")
    return getattr(route, "path", None) or request.url.path


def _request_id(request: Request) -> str:
    """Id de correlación. En AWS lo pone API Gateway y viaja en el evento; en local se genera
    uno para poder seguir una petición entre varias líneas de log."""
    event = request.scope.get("aws.event") or {}
    if isinstance(event, dict):
        from_gateway = event.get("requestContext", {}).get("requestId")
        if from_gateway:
            return str(from_gateway)
    return uuid.uuid4().hex[:12]


class RequestLogMiddleware(BaseHTTPMiddleware):
    """Una línea por petición, con el estado y cuánto tardó."""

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path in _SILENT_PATHS or request.method == "OPTIONS":
            return await call_next(request)
        request_id = _request_id(request)
        request.scope["subastin.request_id"] = request_id
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            # Excepción no controlada: la Lambda la va a reportar igual, pero sin esta línea
            # no queda registro de QUÉ ruta la produjo (el traceback empieza dentro del router).
            logger.exception(
                "http.exception",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "route": _route_template(request),
                    "path": request.url.path,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                },
            )
            raise
        logger.log(
            _level_for(response.status_code),
            "http.request",
            extra={
                "request_id": request_id,
                "method": request.method,
                "route": _route_template(request),
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            },
        )
        return response


async def log_http_exception(request: Request, exc: StarletteHTTPException) -> Response:
    """Registra el MOTIVO del rechazo y deja que FastAPI arme la respuesta de siempre.

    El `detail` lo escribe este backend (no el usuario), así que es seguro loguearlo: es la
    diferencia entre "un 404" y "un 404 porque la conversación no existe". Algunos detalles son
    un dict (el 409 de la toma lleva la conversación actual); de esos solo se guarda su texto,
    para no volcar una entidad entera en el log.
    """
    detail = exc.detail
    if isinstance(detail, dict):
        detail = detail.get("detail")
    logger.log(
        _level_for(exc.status_code),
        "http.error",
        extra={
            "request_id": request.scope.get("subastin.request_id"),
            "method": request.method,
            "route": _route_template(request),
            "path": request.url.path,
            "status": exc.status_code,
            "detail": str(detail) if detail is not None else None,
        },
    )
    return await http_exception_handler(request, exc)


def install(app: FastAPI) -> None:
    """Engancha el log de peticiones a la app. Se llama una vez, en `api/main.py`."""
    app.add_middleware(RequestLogMiddleware)
    app.add_exception_handler(StarletteHTTPException, log_http_exception)
