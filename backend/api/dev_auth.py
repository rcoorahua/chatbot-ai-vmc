"""Imitacion LOCAL del JWT authorizer de Cognito (T1). Solo dev; en Lambda no se instala.

En AWS el flujo es: el HTTP API valida el JWT de Cognito, rechaza con 401 lo que no pase, y
mete los claims en `requestContext.authorizer.jwt.claims` del evento que recibe la Lambda;
Mangum expone ese evento como `scope["aws.event"]`. El backend lee los claims de ahi
(core/auth.py) y nunca toca el token.

Este middleware hace exactamente lo mismo en local para que el codigo de las rutas sea uno
solo: verifica un JWT HS256 firmado con `ADVISOR_DEV_JWT_SECRET` (lo emite
`python -m scripts.advisor_token`) y construye un `aws.event` con la misma forma. Un token
ausente o invalido responde el mismo 401 `{"message": "Unauthorized"}` del API Gateway.

Garantias para no convertirlo en una puerta trasera:
- solo se instala si `ADVISOR_DEV_AUTH=1` Y el proceso no corre en Lambda
  (`AWS_LAMBDA_FUNCTION_NAME` ausente) — main.py lo decide;
- el secreto es propio (no es `SESSION_SIGNING_KEY` ni `VMC_IDENTITY_SECRET`): un token de
  sesion del widget jamas puede colarse como asesor;
- el payload exige `token_use = "id"` y `exp`, como el authorizer.
"""

from __future__ import annotations

import json
import os
from typing import Any

from backend.core import auth
from backend.core.config import get_settings

PROTECTED_PREFIXES = ("/advisor", "/dashboard")


def running_in_lambda() -> bool:
    return bool(os.environ.get("AWS_LAMBDA_FUNCTION_NAME"))


def should_install() -> bool:
    return get_settings().advisor_dev_auth and not running_in_lambda()


def event_with_claims(claims: dict[str, Any]) -> dict[str, Any]:
    """Evento HTTP API v2 minimo, con los claims donde los deja el authorizer real."""
    return {
        "version": "2.0",
        "requestContext": {"authorizer": {"jwt": {"claims": claims, "scopes": None}}},
    }


def verify_dev_token(token: str) -> dict[str, Any]:
    secret = get_settings().advisor_dev_jwt_secret
    if not secret:
        raise auth.IdentityConfigurationError(
            "ADVISOR_DEV_AUTH=1 pero falta ADVISOR_DEV_JWT_SECRET en .env"
        )
    claims = auth.verify_jwt(token, secret)
    if claims.get("token_use") != "id" or not claims.get("sub"):
        raise auth.IdentityError("no es un id token de asesor")
    return claims


class DevCognitoAuthorizer:
    """Middleware ASGI puro (sin BaseHTTPMiddleware: no reenvuelve el body ni el scope)."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith(PROTECTED_PREFIXES):
            await self.app(scope, receive, send)
            return
        # El preflight CORS llega sin Authorization; el API Gateway tampoco lo bloquea.
        if scope["method"] == "OPTIONS":
            await self.app(scope, receive, send)
            return

        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        authorization = headers.get("authorization", "")
        if not authorization.lower().startswith("bearer "):
            await _unauthorized(send)
            return
        try:
            claims = verify_dev_token(authorization[7:].strip())
        except auth.IdentityError:
            await _unauthorized(send)
            return

        scope["aws.event"] = event_with_claims(claims)
        await self.app(scope, receive, send)


async def _unauthorized(send) -> None:
    body = json.dumps({"message": "Unauthorized"}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
