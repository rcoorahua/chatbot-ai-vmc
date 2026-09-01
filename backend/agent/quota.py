"""Tope de ejecuciones de IA por actor — T-09 / D-027 (revisada 2026-09-01 por Aaron).

Complementa el rate limit de D-005 (por minuto y por conversacion): esto frena el costo
ACUMULADO de un mismo actor. Sin este tope, el freno de 10 mensajes/min permite 14 400
llamadas de IA al dia desde una sola pestana anonima con un script.

Reglas (todas configurables; 0 = sin tope, y ASI QUEDA EN DEV por ahora):

- Se cuenta el MENSAJE QUE LLAMO A UN MODELO, no el mensaje a secas: triviales, guardrails,
  reglas deterministas y ofrecer botones de flujo no gastan porque no cuestan.
- Anonimo: por sesion (= conversation_id, D-002/D-018) Y por hash de IP — se agota la primera
  de las dos. CGNAT: muchos usuarios legitimos comparten IP publica (moviles, oficinas); por
  eso el autenticado NUNCA se cuenta por IP, sino por user_id, y el anonimo tiene tambien el
  contador de sesion para no depender solo de la IP.
- Autenticado: el doble de cuota, por user_id.
- Ventanas deslizantes por hora natural y por dia natural (UTC), en la tabla RateLimits
  (PK `USER#…`/`SESSION#…`/`IP#…`, SK `H#2026-09-01T19` / `D#2026-09-01`), con TTL de 48 h
  en AWS para que DynamoDB borre los contadores solos.
- La IP se guarda SOLO hasheada (HMAC-SHA256 con `IP_HASH_SECRET`, o `SESSION_SIGNING_KEY`
  si no hay): es dato personal y para contar da igual el valor real.
- Este modulo NUNCA lanza hacia el pipeline: si la tabla falla, el bot responde igual —
  perder un conteo es mejor que dejar al usuario sin respuesta por culpa del contador.
"""

from __future__ import annotations

import hashlib
import hmac
import logging

from backend.core.aws import dynamodb_resource
from backend.core.clock import epoch_seconds, utc_now_iso
from backend.core.config import get_settings

logger = logging.getLogger(__name__)

# TTL de los contadores: la ventana mas larga es un dia; 48 h da margen de sobra para
# depurar sin acumular filas para siempre.
_TTL_SECONDS = 48 * 3600


def _table():
    return dynamodb_resource().Table(get_settings().table_rate_limits)


def hash_ip(ip: str | None) -> str | None:
    """HMAC de la IP, troncado a 32 hex. None entra, None sale (sin IP no hay contador IP)."""
    if not ip:
        return None
    settings = get_settings()
    secret = settings.ip_hash_secret or settings.session_signing_key or ""
    if not secret:
        # Sin secreto no se hashea nada — y sin hash no se cuenta por IP. Preferible a
        # guardar la IP en claro o a un hash sin llave que se revierte por diccionario.
        return None
    return hmac.new(secret.encode(), ip.encode(), hashlib.sha256).hexdigest()[:32]


def _limits(anonymous: bool) -> tuple[int, int]:
    """(por_hora, por_dia) segun el tipo de usuario. 0 = esa ventana no aplica."""
    settings = get_settings()
    if anonymous:
        return settings.ai_quota_anon_per_hour, settings.ai_quota_anon_per_day
    return settings.ai_quota_auth_per_hour, settings.ai_quota_auth_per_day


def _keys(*, anonymous: bool, user_id: str | None, conversation_id: str,
          ip_hash: str | None) -> list[str]:
    """Los contadores que aplican a este actor. Autenticado: solo user_id (preciso y no se
    comparte). Anonimo: sesion + IP hasheada — se agota la primera (D-027)."""
    if not anonymous and user_id:
        return [f"USER#{user_id}"]
    keys = [f"SESSION#{conversation_id}"]
    if ip_hash:
        keys.append(f"IP#{ip_hash}")
    return keys


def _windows() -> list[tuple[str, int]]:
    """[(SK, limite_idx)]: la ventana horaria (idx 0) y la diaria (idx 1), en hora UTC."""
    now = utc_now_iso()  # "2026-09-01T19:27:10.699Z"
    return [(f"H#{now[:13]}", 0), (f"D#{now[:10]}", 1)]


def enabled(*, anonymous: bool) -> bool:
    """Hay algun tope configurado para este tipo de usuario. Con todo en 0 (dev) el pipeline
    no toca la tabla: cero lecturas, cero escrituras, cero latencia extra."""
    per_hour, per_day = _limits(anonymous)
    return per_hour > 0 or per_day > 0


def exhausted(*, anonymous: bool, user_id: str | None, conversation_id: str,
              ip_hash: str | None) -> bool:
    """El actor ya no tiene ejecuciones de IA disponibles en alguna de sus ventanas.

    Lectura simple (sin transaccion): la carrera de un mensaje concurrente puede dejar pasar
    una llamada de mas, aceptable para control de costos — esto no es facturacion.
    """
    limits = _limits(anonymous)
    if limits[0] <= 0 and limits[1] <= 0:
        return False
    table = _table()
    try:
        for key in _keys(anonymous=anonymous, user_id=user_id,
                         conversation_id=conversation_id, ip_hash=ip_hash):
            for window, limit_idx in _windows():
                limit = limits[limit_idx]
                if limit <= 0:
                    continue
                item = table.get_item(
                    Key={"limit_key": key, "window": window}
                ).get("Item")
                if item and int(item.get("calls", 0)) >= limit:
                    logger.info(
                        "ai.quota.exhausted",
                        extra={"limit_key": key, "window": window, "limit": limit},
                    )
                    return True
    except Exception:  # noqa: BLE001 — ver docstring del modulo: el contador nunca bloquea
        logger.exception("No se pudo leer la cuota de IA; se deja pasar")
        return False
    return False


def spend(*, anonymous: bool, user_id: str | None, conversation_id: str,
          ip_hash: str | None) -> None:
    """Registra UNA ejecucion de IA en todas las ventanas del actor (ADD atomico)."""
    if not enabled(anonymous=anonymous):
        return
    table = _table()
    expires_at = epoch_seconds() + _TTL_SECONDS
    try:
        for key in _keys(anonymous=anonymous, user_id=user_id,
                         conversation_id=conversation_id, ip_hash=ip_hash):
            for window, _limit_idx in _windows():
                table.update_item(
                    Key={"limit_key": key, "window": window},
                    UpdateExpression="ADD calls :one SET expires_at = :ttl",
                    ExpressionAttributeValues={":one": 1, ":ttl": expires_at},
                )
    except Exception:  # noqa: BLE001
        logger.exception("No se pudo registrar la cuota de IA; se sigue igual")
