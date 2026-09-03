"""Identidad del chat publico (D-001, cerrada 2026-08-27) y sesion del widget.

Como llega la identidad — mismo esquema que la "identity verification" de Intercom, en su
variante actual con JWT:

    1. El SERVIDOR de VMC (unico que conoce el secreto compartido `VMC_IDENTITY_SECRET`) firma
       un JWT HS256 con `sub` = id del usuario VMC, `name`, `email` y `exp`, y lo deja en la
       pagina como `window.subastinSettings.userJwt`.
    2. El widget lo manda a `POST /chat/sessions`. Aqui se verifica la firma y la expiracion;
       el `sub` es la identidad (RF-005 / AC-008).
    3. Subastin responde con SU PROPIO token de sesion (firmado con `SESSION_SIGNING_KEY`), que
       el widget usa como Bearer en el resto de llamadas. Para anonimos el paso 1 no existe y
       el token de sesion es lo unico que los identifica mientras dure (RF-004 / D-018).

Por que asi y no leyendo la cookie de VMC: `subastop_jwt` es HttpOnly, asi que ningun script
del widget puede leerla, y compartir el secreto con el que VMC firma sus sesiones permitiria a
Subastin forjar sesiones de VMC. Un JWT aparte, firmado con un secreto aparte, solo sirve para
el chat. RNF-005 queda cubierto: nada de lo que manda el frontend se cree sin firma.

Los dos tokens son JWT HS256 armados con la biblioteca estandar: son 3 partes base64url y una
HMAC; una dependencia mas no aporta nada aqui.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, Header, HTTPException, Request, status

from backend.core.clock import epoch_seconds
from backend.core.config import get_settings

USER_TYPE_AUTHENTICATED = "AUTHENTICATED"
USER_TYPE_ANONYMOUS = "ANONYMOUS"

_MAX_NAME_CHARS = 120
_MAX_EMAIL_CHARS = 254
_MAX_USER_ID_CHARS = 64


class IdentityError(Exception):
    """El token no es valido (firma, formato, expiracion o claims). Se responde 401."""


class IdentityConfigurationError(RuntimeError):
    """Falta un secreto en la configuracion: error de despliegue, no del usuario (503)."""


@dataclass(frozen=True, slots=True)
class VmcIdentity:
    """Usuario VMC ya verificado. Es la unica forma de obtener un `user_id` confiable."""

    user_id: str
    name: str | None = None
    email: str | None = None


@dataclass(frozen=True, slots=True)
class ChatSession:
    """Lo que el token de sesion del widget afirma; cada request lo recibe ya verificado."""

    session_id: str
    user_type: str
    conversation_id: str
    user_id: str | None
    user_name: str | None
    expires_at: int

    @property
    def is_authenticated(self) -> bool:
        return self.user_type == USER_TYPE_AUTHENTICATED


# ───────────────────────────────── JWT HS256 minimo ─────────────────────────────────


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    try:
        return base64.urlsafe_b64decode(text + padding)
    except (binascii.Error, ValueError) as exc:
        raise IdentityError("token mal formado") from exc


def sign_jwt(payload: dict[str, Any], secret: str) -> str:
    header = _b64url_encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode())
    signature = hmac.new(secret.encode(), f"{header}.{body}".encode(), hashlib.sha256).digest()
    return f"{header}.{body}.{_b64url_encode(signature)}"


def verify_jwt(token: str, secret: str, *, now: int | None = None) -> dict[str, Any]:
    """Devuelve el payload si la firma es valida y no expiro; si no, IdentityError.

    `exp` es obligatorio: un token sin caducidad es una credencial permanente, y ni el JWT de
    VMC ni el de sesion deberian serlo.
    """
    parts = token.split(".")
    if len(parts) != 3 or not all(parts):
        raise IdentityError("token mal formado")
    header_b64, body_b64, signature_b64 = parts

    try:
        header = json.loads(_b64url_decode(header_b64))
    except ValueError as exc:
        raise IdentityError("cabecera ilegible") from exc
    # Aceptar el `alg` que declare el token es el fallo clasico de JWT (`alg: none`). Aqui solo
    # existe HS256 y cualquier otra cosa es un intento de saltarse la firma.
    if not isinstance(header, dict) or header.get("alg") != "HS256":
        raise IdentityError("algoritmo no soportado")

    expected = hmac.new(
        secret.encode(), f"{header_b64}.{body_b64}".encode(), hashlib.sha256
    ).digest()
    if not hmac.compare_digest(expected, _b64url_decode(signature_b64)):
        raise IdentityError("firma invalida")

    try:
        payload = json.loads(_b64url_decode(body_b64))
    except ValueError as exc:
        raise IdentityError("payload ilegible") from exc
    if not isinstance(payload, dict):
        raise IdentityError("payload ilegible")

    exp = payload.get("exp")
    if not isinstance(exp, int | float):
        raise IdentityError("falta exp")
    if exp <= (now if now is not None else epoch_seconds()):
        raise IdentityError("token expirado")
    return payload


# ───────────────────────────── Identidad VMC (paso 1 y 2) ─────────────────────────────


def _clean_text(value: Any, max_chars: int) -> str | None:
    """Los claims vienen firmados por VMC, pero el tamaño no: se acota antes de persistir."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text[:max_chars] if text else None


def verify_vmc_identity(user_jwt: str) -> VmcIdentity:
    secret = get_settings().vmc_identity_secret
    if not secret:
        raise IdentityConfigurationError("Falta VMC_IDENTITY_SECRET")

    payload = verify_jwt(user_jwt, secret)
    # `sub` es el claim estandar; `user_id` es el nombre que usa Intercom en su JWT de
    # identidad. Aceptar ambos deja que VMC reutilice el codigo que ya firma ese token,
    # cambiando solo el secreto.
    user_id = _clean_text(payload.get("sub") or payload.get("user_id"), _MAX_USER_ID_CHARS)
    if user_id is None:
        raise IdentityError("falta sub")
    return VmcIdentity(
        user_id=user_id,
        name=_clean_text(payload.get("name"), _MAX_NAME_CHARS),
        email=_clean_text(payload.get("email"), _MAX_EMAIL_CHARS),
    )


# ───────────────────────────── Token de sesion del widget (paso 3) ─────────────────────────────


def _signing_key() -> str:
    key = get_settings().session_signing_key
    if not key:
        raise IdentityConfigurationError("Falta SESSION_SIGNING_KEY")
    return key


def ensure_session_signing_configured() -> None:
    """Falla temprano si falta `SESSION_SIGNING_KEY`, ANTES de crear nada (DETAILS.md §4.2):
    sin este chequeo, `create_session` abria la conversacion (fila real, tambien para el
    anonimo) y recien despues intentaba firmar el token — un 503 dejaba una fila huerfana en
    cada intento mientras el secreto siguiera sin configurar."""
    _signing_key()


def new_session(
    *,
    user_type: str,
    conversation_id: str,
    user_id: str | None,
    user_name: str | None,
) -> ChatSession:
    settings = get_settings()
    hours = (
        settings.session_ttl_hours
        if user_type == USER_TYPE_AUTHENTICATED
        else settings.anonymous_session_ttl_hours
    )
    return ChatSession(
        session_id=uuid.uuid4().hex,
        user_type=user_type,
        conversation_id=conversation_id,
        user_id=user_id,
        user_name=user_name,
        expires_at=epoch_seconds() + hours * 3600,
    )


def issue_session_token(session: ChatSession) -> str:
    payload = {
        "sid": session.session_id,
        "typ": session.user_type,
        "cid": session.conversation_id,
        "sub": session.user_id,
        "name": session.user_name,
        "iat": epoch_seconds(),
        "exp": session.expires_at,
    }
    return sign_jwt(payload, _signing_key())


def decode_session_token(token: str) -> ChatSession:
    payload = verify_jwt(token, _signing_key())
    user_type = payload.get("typ")
    conversation_id = payload.get("cid")
    if user_type not in (USER_TYPE_AUTHENTICATED, USER_TYPE_ANONYMOUS) or not isinstance(
        conversation_id, str
    ):
        raise IdentityError("sesion incompleta")
    return ChatSession(
        session_id=str(payload.get("sid") or ""),
        user_type=user_type,
        conversation_id=conversation_id,
        user_id=_clean_text(payload.get("sub"), _MAX_USER_ID_CHARS),
        user_name=_clean_text(payload.get("name"), _MAX_NAME_CHARS),
        expires_at=int(payload["exp"]),
    )


def get_chat_session(
    authorization: Annotated[str | None, Header()] = None,
) -> ChatSession:
    """Dependency de FastAPI: `Authorization: Bearer <token de sesion>` o 401."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Falta el token de sesion")
    try:
        return decode_session_token(authorization[7:].strip())
    except IdentityError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Sesion invalida: {exc}") from exc
    except IdentityConfigurationError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc


CurrentSession = Annotated[ChatSession, Depends(get_chat_session)]


# ───────────────────────────── Asesores: claims de Cognito (T1) ─────────────────────────────
#
# El JWT de Cognito NO se valida aqui. Lo valida el JWT authorizer del HTTP API antes de invocar
# la Lambda, y Mangum deja el evento completo en `request.scope["aws.event"]`; los claims viven
# en `requestContext.authorizer.jwt.claims`. Si ese camino no trae claims, la ruta es 401: un
# request sin authorizer solo puede ser una mala configuracion del stack o un despliegue que
# expuso /advisor sin proteger, y en ambos casos rechazar es lo correcto.
#
# En local no hay API Gateway: backend/api/dev_auth.py imita al authorizer y deja los claims en
# el mismo sitio, asi que este codigo no distingue entornos.

_MAX_SUB_CHARS = 128


class AdvisorAuthError(Exception):
    """El request no trae claims de Cognito (o vienen incompletos). Se responde 401."""


@dataclass(frozen=True, slots=True)
class CognitoClaims:
    """Lo minimo que el authorizer garantiza de un asesor autenticado."""

    sub: str
    email: str | None = None
    name: str | None = None


def cognito_claims_from_event(event: Any) -> CognitoClaims:
    """Extrae los claims del evento HTTP API v2 (payload 2.0) que recibe la Lambda."""
    if not isinstance(event, dict):
        raise AdvisorAuthError("el request no paso por el authorizer")
    claims = (
        event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    )
    if not isinstance(claims, dict) or not claims:
        raise AdvisorAuthError("el request no trae claims de Cognito")
    sub = str(claims.get("sub") or "").strip()
    if not sub or len(sub) > _MAX_SUB_CHARS:
        raise AdvisorAuthError("claims sin sub")
    email = claims.get("email")
    name = claims.get("name") or claims.get("cognito:username")
    return CognitoClaims(
        sub=sub,
        email=str(email)[:_MAX_EMAIL_CHARS] if email else None,
        name=str(name)[:_MAX_NAME_CHARS] if name else None,
    )


def get_cognito_claims(request: Request) -> CognitoClaims:
    """Dependency de FastAPI para las rutas `/advisor` y `/dashboard`."""
    try:
        return cognito_claims_from_event(request.scope.get("aws.event"))
    except AdvisorAuthError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc


CurrentClaims = Annotated[CognitoClaims, Depends(get_cognito_claims)]
