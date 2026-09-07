"""Contadores atomicos en la tabla RateLimits: UN solo dueño de sus claves.

La tabla la comparten dos cosas que no pueden importarse entre si: la cuota de ejecuciones
de IA por actor (`agent/quota.py`, D-027) y el tope de casos abiertos por usuario
(`conversations/repository.py`, D-029, Paso 6). Antes cada uno escribia el formato de la
clave por su cuenta (auditoria 2026-09-06); aqui esta la forma de la fila y los items de
transaccion, y cada modulo conserva su logica.

    PK `limit_key`: `<PREFIJO>#<actor>`   (USER#…, SESSION#…, IP#…, OPEN_CASES#USER#…)
    SK `window`:    `H#2026-09-01T19` / `D#2026-09-01` (ventanas UTC) o `LIVE` (sin ventana)
    `calls` / `open_cases`: el contador; `expires_at`: TTL (48 h) para las ventanas.

El esquema de la tabla esta duplicado a proposito en infra/stacks/subastin_stack.py y
scripts/local_setup.py (invariante de CLAUDE.md).
"""

from __future__ import annotations

from typing import Any

from backend.core.aws import dynamodb_resource
from backend.core.config import get_settings

# TTL de los contadores por ventana: la mas larga es un dia; 48 h da margen de sobra para
# depurar sin acumular filas para siempre.
TTL_SECONDS = 48 * 3600
# Ventana de los contadores que no vencen (el cupo de casos abiertos vive lo que el usuario).
LIVE_WINDOW = "LIVE"


def table():
    return dynamodb_resource().Table(get_settings().table_rate_limits)


def key(prefix: str, actor: str) -> str:
    return f"{prefix}#{actor}"


def open_cases_key(user_id: str) -> str:
    return key("OPEN_CASES#USER", user_id)


def reserve_open_case_item(user_id: str, limit: int) -> dict[str, Any]:
    """Item de `TransactWriteItems` que reserva un cupo de caso abierto: `ADD` condicionado a
    seguir bajo el limite. Si la condicion falla, el que la transaccion lo reporte en ESTE
    item es lo que significa "tope alcanzado"."""
    return {
        "Update": {
            "TableName": get_settings().table_rate_limits,
            "Key": {"limit_key": open_cases_key(user_id), "window": LIVE_WINDOW},
            "UpdateExpression": "ADD open_cases :one",
            "ConditionExpression": "attribute_not_exists(open_cases) OR open_cases < :limit",
            "ExpressionAttributeValues": {":one": 1, ":limit": limit},
        }
    }


def release_open_case_item(user_id: str) -> dict[str, Any]:
    """Item de `TransactWriteItems` que libera el cupo al cerrar el caso."""
    return {
        "Update": {
            "TableName": get_settings().table_rate_limits,
            "Key": {"limit_key": open_cases_key(user_id), "window": LIVE_WINDOW},
            "UpdateExpression": "ADD open_cases :minus_one",
            "ExpressionAttributeValues": {":minus_one": -1},
        }
    }
