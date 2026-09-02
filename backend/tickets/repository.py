"""UNICO lugar que conoce claves/GSIs de Tickets (PLAN.md §4).

Patrones que viven aquí y en ningún otro sitio:
- ticket por id (PK) y por conversación (GSI1 `conversation_id`/`created_at`);
- bandeja por estado (GSI3 `status`/`created_at`, el que más espera primero) y tickets de un
  asesor (GSI2 `assigned_advisor_id`/`updated_at`);
- creación condicional por conversación: dos requests simultáneos (el handoff y la red de
  seguridad `ensure_ticket`) no pueden dejar dos tickets del mismo caso.

Los tests de este módulo corren contra dynamodb-local real: un GSI mal usado falla aquí.
"""

from typing import Any

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from backend.core.aws import dynamodb_resource
from backend.core.config import get_settings
from backend.tickets.models import Ticket


class TicketNotFound(LookupError):
    pass


def _tickets():
    return dynamodb_resource().Table(get_settings().table_tickets)


def _is_condition_failure(exc: ClientError) -> bool:
    return exc.response["Error"]["Code"] == "ConditionalCheckFailedException"


def get_ticket(ticket_id: str) -> Ticket | None:
    item = _tickets().get_item(Key={"ticket_id": ticket_id}).get("Item")
    return Ticket.from_item(item) if item else None


def find_by_conversation(conversation_id: str) -> Ticket | None:
    """El ticket de una conversación escalada (GSI1). Es 1:1 (ver `tickets/models.py`), pero
    se consulta ordenado y se devuelve el más reciente: si alguna vez hubiera dos por una
    carrera perdida, gana el último y ninguno se pierde de la tabla."""
    response = _tickets().query(
        IndexName="gsi1_conversation",
        KeyConditionExpression=Key("conversation_id").eq(conversation_id),
        ScanIndexForward=False,
        Limit=1,
    )
    items = response["Items"]
    return Ticket.from_item(items[0]) if items else None


def create_ticket(ticket: Ticket) -> bool:
    """Crea el ticket si su id no existe. Devuelve False si otro request ganó la carrera."""
    try:
        _tickets().put_item(
            Item=ticket.to_item(),
            ConditionExpression="attribute_not_exists(ticket_id)",
        )
    except ClientError as exc:
        if _is_condition_failure(exc):
            return False
        raise
    return True


def list_inbox(status: str | None = None, *, limit: int = 50) -> list[Ticket]:
    """Bandeja de tickets por estado (GSI3). Los pendientes salen del más antiguo al más
    nuevo: el que más espera va primero, igual que la bandeja de conversaciones (RF-032)."""
    if status is None:
        # Sin filtro: pendientes primero y después los que ya están en atención. CLOSED queda
        # fuera a propósito — la bandeja es trabajo por hacer, no historial.
        pendientes = list_inbox("PENDING", limit=limit)
        en_curso = list_inbox("IN_PROGRESS", limit=limit)
        return (pendientes + en_curso)[:limit]
    response = _tickets().query(
        IndexName="gsi3_status",
        KeyConditionExpression=Key("status").eq(status),
        ScanIndexForward=status == "PENDING",
        Limit=limit,
    )
    return [Ticket.from_item(item) for item in response["Items"]]


def find_by_advisor(advisor_id: str, *, limit: int = 50) -> list[Ticket]:
    """Tickets de un asesor, el más reciente primero (GSI2)."""
    response = _tickets().query(
        IndexName="gsi2_advisor",
        KeyConditionExpression=Key("assigned_advisor_id").eq(advisor_id),
        ScanIndexForward=False,
        Limit=limit,
    )
    return [Ticket.from_item(item) for item in response["Items"]]


def update_ticket(
    ticket_id: str, changes: dict[str, Any], *, expected_status: str | None = None
) -> Ticket | None:
    """Aplica `changes` sobre el ticket y devuelve la fila resultante.

    `expected_status` hace la escritura condicional: así "cerrar" no revive un ticket ya
    cerrado por otro asesor ni pisa un cambio de estado que ocurrió entre la lectura y la
    escritura. Devuelve None si la condición falla.
    """
    if not changes:
        return get_ticket(ticket_id)
    sets: list[str] = []
    removes: list[str] = []
    values: dict[str, Any] = {}
    names: dict[str, str] = {}
    for index, (field, value) in enumerate(changes.items()):
        placeholder = f"#f{index}"
        names[placeholder] = field
        if value is None:
            removes.append(placeholder)
            continue
        sets.append(f"{placeholder} = :v{index}")
        values[f":v{index}"] = value
    expression = ("SET " + ", ".join(sets) if sets else "") + (
        (" " if sets else "") + "REMOVE " + ", ".join(removes) if removes else ""
    )
    kwargs: dict[str, Any] = {
        "Key": {"ticket_id": ticket_id},
        "UpdateExpression": expression,
        "ExpressionAttributeNames": names,
        "ReturnValues": "ALL_NEW",
    }
    if values:
        kwargs["ExpressionAttributeValues"] = values
    if expected_status is not None:
        kwargs["ConditionExpression"] = "#status_check = :expected_status"
        names["#status_check"] = "status"
        kwargs.setdefault("ExpressionAttributeValues", {})[":expected_status"] = expected_status
    try:
        response = _tickets().update_item(**kwargs)
    except ClientError as exc:
        if _is_condition_failure(exc):
            return None
        raise
    return Ticket.from_item(response["Attributes"])
