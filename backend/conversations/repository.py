"""UNICO lugar que conoce claves/GSIs de Conversations y Messages (PLAN.md §4).

Patrones que viven aqui y en ningun otro sitio:
- conversacion por id (PK) y por usuario (GSI1 `user_id`/`updated_at`);
- creacion condicional (`attribute_not_exists`) para que dos pestañas abiertas a la vez no
  creen dos conversaciones para el mismo usuario (D-002: maximo 1);
- guardado IDEMPOTENTE del mensaje entrante: una transaccion con item marcador
  `CMID#<client_message_id>` + el mensaje + los contadores de la conversacion (ajuste 4 de
  REQUERIMENTS.md §1.11, validado en tests/test_dynamo_queries.py);
- listado cronologico por SK y ventana reciente para la IA (RF-013), ambos dejando fuera los
  marcadores de idempotencia;
- bandeja por estado (GSI2) y casos de un asesor (GSI3) para RF-032;
- toma ATOMICA de la conversacion (AC-005) y cierre del caso: un UpdateItem condicional sobre
  la conversacion + la nota SYSTEM en el hilo, en una sola transaccion;
- historial hacia atras para el asesor (RF-012): ultimos N y paginas anteriores con `before`.

Los tests de este modulo corren contra dynamodb-local real: un GSI mal usado falla aqui.
"""

from typing import Any

from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

from backend.conversations.models import (
    IDEMPOTENCY_KEY_PREFIX,
    Conversation,
    Message,
    MessageStatus,
    idempotency_key_for,
)
from backend.core.aws import dynamodb_resource
from backend.core.config import get_settings

# Toda SK de mensaje empieza por el año (`2026-...`); los marcadores empiezan por `CMID#`, que
# ordena despues. Acotar la SK por arriba con "3" saca los marcadores de la consulta sin
# filtro (un filtro se aplica DESPUES del Limit y devolveria paginas cortas).
_LAST_MESSAGE_KEY = "3"
_FIRST_MESSAGE_KEY = "0"
_PREVIEW_CHARS = 120


class ConversationNotFound(LookupError):
    pass


def _conversations():
    return dynamodb_resource().Table(get_settings().table_conversations)


def _messages():
    return dynamodb_resource().Table(get_settings().table_messages)


def _is_condition_failure(exc: ClientError) -> bool:
    return exc.response["Error"]["Code"] == "ConditionalCheckFailedException"


# ───────────────────────────────────── Conversations ─────────────────────────────────────


def get_conversation(conversation_id: str) -> Conversation | None:
    item = _conversations().get_item(Key={"conversation_id": conversation_id}).get("Item")
    return Conversation.from_item(item) if item else None


def find_conversations_by_user(user_id: str, *, limit: int = 10) -> list[Conversation]:
    """Conversaciones de un usuario autenticado, mas reciente primero (GSI1, RF-012)."""
    response = _conversations().query(
        IndexName="gsi1_user",
        KeyConditionExpression=Key("user_id").eq(user_id),
        ScanIndexForward=False,
        Limit=limit,
    )
    return [Conversation.from_item(item) for item in response["Items"]]


def list_inbox(status: str, *, limit: int = 50, oldest_first: bool = True) -> list[Conversation]:
    """Bandeja por estado (GSI2, RF-032). Los pendientes salen del mas antiguo al mas nuevo:
    el que mas espera va primero."""
    response = _conversations().query(
        IndexName="gsi2_inbox",
        KeyConditionExpression=Key("status").eq(status),
        ScanIndexForward=oldest_first,
        Limit=limit,
    )
    return [Conversation.from_item(item) for item in response["Items"]]


def find_conversations_by_advisor(advisor_id: str, *, limit: int = 50) -> list[Conversation]:
    """Casos asignados a un asesor, mas reciente primero (GSI3)."""
    response = _conversations().query(
        IndexName="gsi3_advisor",
        KeyConditionExpression=Key("assigned_advisor_id").eq(advisor_id),
        ScanIndexForward=False,
        Limit=limit,
    )
    return [Conversation.from_item(item) for item in response["Items"]]


def create_conversation(conversation: Conversation) -> bool:
    """Crea la conversacion si no existe. Devuelve False si otro request gano la carrera."""
    try:
        _conversations().put_item(
            Item=conversation.to_item(),
            ConditionExpression="attribute_not_exists(conversation_id)",
        )
    except ClientError as exc:
        if _is_condition_failure(exc):
            return False
        raise
    return True


def update_user_profile(
    conversation_id: str, *, user_name: str | None, user_email: str | None, updated_at: str
) -> None:
    """Refresca la copia minima del usuario (VMC es la fuente de verdad, RF-051)."""
    sets = ["updated_at = :updated_at"]
    values: dict[str, Any] = {":updated_at": updated_at}
    if user_name is not None:
        sets.append("user_name = :user_name")
        values[":user_name"] = user_name
    if user_email is not None:
        sets.append("user_email = :user_email")
        values[":user_email"] = user_email
    _conversations().update_item(
        Key={"conversation_id": conversation_id},
        UpdateExpression="SET " + ", ".join(sets),
        ExpressionAttributeValues=values,
    )


def reset_unread(conversation_id: str) -> None:
    """RF-035: al abrir el hilo, los no leidos quedan consumidos. Condicional para no escribir
    en cada sondeo cuando ya esta en cero."""
    try:
        _conversations().update_item(
            Key={"conversation_id": conversation_id},
            UpdateExpression="SET unread_count = :zero",
            ConditionExpression="unread_count > :zero",
            ExpressionAttributeValues={":zero": 0},
        )
    except ClientError as exc:
        if not _is_condition_failure(exc):
            raise


def assign_advisor(
    conversation_id: str, advisor_id: str, *, allowed_statuses: list[str], note: Message
) -> bool:
    """Toma atomica (AC-005): asigna, pasa a IN_ATTENTION y apaga el bot solo si nadie la tiene
    y el estado lo permite; en la misma transaccion deja la nota SYSTEM en el hilo. Devuelve
    False si otro asesor gano la carrera (o el estado ya no es tomable)."""
    placeholders = {f":s{i}": value for i, value in enumerate(allowed_statuses)}
    update = _touch_conversation_update(conversation_id, note, count_as_unread=False)["Update"]
    update["UpdateExpression"] += (
        ", assigned_advisor_id = :advisor, #status = :in_attention, bot_enabled = :off"
    )
    update["ConditionExpression"] = (
        "attribute_exists(conversation_id) AND attribute_not_exists(assigned_advisor_id) "
        f"AND #status IN ({', '.join(placeholders)})"
    )
    update["ExpressionAttributeNames"] = {"#status": "status"}
    update["ExpressionAttributeValues"].update(
        {":advisor": advisor_id, ":in_attention": "IN_ATTENTION", ":off": False, **placeholders}
    )
    return _transact_note(update, note)


def release_advisor(conversation_id: str, advisor_id: str, *, note: Message) -> bool:
    """Cierre del caso (RF-031 con D-003): la conversacion NO se cierra, vuelve a BOT_ATTENDING
    con el bot encendido y sin asesor; la nota SYSTEM `TICKET_CLOSED` queda en el hilo. Solo el
    asesor asignado puede cerrar. Devuelve False si no es el asignado."""
    update = _touch_conversation_update(conversation_id, note, count_as_unread=False)["Update"]
    update["UpdateExpression"] += (
        ", #status = :bot_attending, bot_enabled = :on, wait_message_sent = :off, "
        "unread_count = :zero REMOVE assigned_advisor_id, handoff_requested_at, handoff_reason"
    )
    update["ConditionExpression"] = "assigned_advisor_id = :advisor"
    update["ExpressionAttributeNames"] = {"#status": "status"}
    update["ExpressionAttributeValues"].update(
        {
            ":advisor": advisor_id,
            ":bot_attending": "BOT_ATTENDING",
            ":on": True,
            ":off": False,
            ":zero": 0,
        }
    )
    return _transact_note(update, note)


def _transact_note(conversation_update: dict[str, Any], note: Message) -> bool:
    """Update condicional de la conversacion + Put de la nota SYSTEM, todo o nada."""
    client = dynamodb_resource().meta.client
    try:
        client.transact_write_items(
            TransactItems=[
                {"Update": conversation_update},
                {"Put": {"TableName": get_settings().table_messages, "Item": note.to_item()}},
            ]
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "TransactionCanceledException":
            raise
        reasons = [r.get("Code") for r in exc.response.get("CancellationReasons", [])]
        if reasons and reasons[0] == "ConditionalCheckFailed":
            return False
        raise
    return True


# ─────────────────────────────────────── Messages ───────────────────────────────────────


def get_message(conversation_id: str, message_key: str) -> Message | None:
    item = _messages().get_item(
        Key={"conversation_id": conversation_id, "message_key": message_key}
    ).get("Item")
    return Message.from_item(item) if item else None


def find_message_by_client_id(conversation_id: str, client_message_id: str) -> Message | None:
    """Resuelve un reintento: del marcador al mensaje real que se guardo la primera vez."""
    marker = _messages().get_item(
        Key={
            "conversation_id": conversation_id,
            "message_key": idempotency_key_for(client_message_id),
        }
    ).get("Item")
    if not marker:
        return None
    return get_message(conversation_id, marker["target_message_key"])


def list_messages(
    conversation_id: str, *, after: str | None = None, limit: int = 50
) -> list[Message]:
    """Mensajes en orden cronologico. `after` es exclusivo: el sondeo del widget pasa la SK del
    ultimo mensaje que ya tiene y recibe solo lo nuevo."""
    lower = after or _FIRST_MESSAGE_KEY
    response = _messages().query(
        KeyConditionExpression=Key("conversation_id").eq(conversation_id)
        & Key("message_key").between(lower, _LAST_MESSAGE_KEY),
        ScanIndexForward=True,
        # `between` incluye el extremo inferior; se pide uno mas y se descarta `after`.
        Limit=limit + 1 if after else limit,
    )
    messages = [Message.from_item(item) for item in response["Items"]]
    if after and messages and messages[0].message_key == after:
        messages = messages[1:]
    return messages[:limit]


def list_recent_messages(
    conversation_id: str, *, limit: int = 20, since: str | None = None
) -> list[Message]:
    """Los ultimos N mensajes en orden natural: la ventana de contexto de la IA (RF-013).

    `since` es el corte temporal de D-004 (un ISO-8601 del mismo formato que la SK): solo entra
    lo posterior. Va en la KeyConditionExpression, no como filtro, porque un filtro se aplica
    DESPUES del Limit y devolveria menos mensajes de los pedidos.

    Se consulta descendente con Limit y se reinvierte. La cota superior de la SK importa aun
    mas aqui: en orden descendente los marcadores `CMID#` saldrian PRIMERO y se comerian el
    Limit, devolviendo una ventana llena de marcadores en vez de mensajes.
    """
    response = _messages().query(
        KeyConditionExpression=Key("conversation_id").eq(conversation_id)
        & Key("message_key").between(since or _FIRST_MESSAGE_KEY, _LAST_MESSAGE_KEY),
        ScanIndexForward=False,
        Limit=limit,
    )
    return [Message.from_item(item) for item in reversed(response["Items"])]


def count_messages_since(conversation_id: str, *, since: str, sender_type: str) -> int:
    """Cuantos mensajes de ese remitente hay desde `since`. Base del rate limit (RF-014).

    Cuenta contra la tabla en vez de un contador aparte: la ventana es de un minuto, asi que
    son pocos items, y no hay que mantener ningun estado que pueda quedar desincronizado.
    `Select=COUNT` no trae los items, solo el numero.
    """
    response = _messages().query(
        KeyConditionExpression=Key("conversation_id").eq(conversation_id)
        & Key("message_key").between(since, _LAST_MESSAGE_KEY),
        FilterExpression=Attr("sender_type").eq(sender_type),
        Select="COUNT",
    )
    return int(response.get("Count", 0))


def list_messages_before(
    conversation_id: str, *, before: str | None = None, limit: int = 20
) -> tuple[list[Message], bool]:
    """Historial hacia atras para el asesor (RF-012): los `limit` mensajes anteriores a `before`
    (exclusivo; None = los ultimos), en orden cronologico, y si queda mas historia detras.

    Se pide uno de mas para saber si hay otra pagina sin una segunda consulta.
    """
    upper = before or _LAST_MESSAGE_KEY
    response = _messages().query(
        KeyConditionExpression=Key("conversation_id").eq(conversation_id)
        & Key("message_key").between(_FIRST_MESSAGE_KEY, upper),
        ScanIndexForward=False,
        Limit=limit + 2 if before else limit + 1,
    )
    items = [Message.from_item(item) for item in response["Items"]]
    if before and items and items[0].message_key == before:
        items = items[1:]
    has_more = len(items) > limit
    return list(reversed(items[:limit])), has_more


def _touch_conversation_update(
    conversation_id: str, message: Message, *, count_as_unread: bool
) -> dict[str, Any]:
    """Update de los campos desnormalizados de la conversacion, para meter en la transaccion."""
    expression = (
        "SET message_count = message_count + :one, last_message_at = :at, "
        "last_message_preview = :preview, updated_at = :at"
    )
    if count_as_unread:
        expression += ", unread_count = unread_count + :one"
    return {
        "Update": {
            "TableName": get_settings().table_conversations,
            "Key": {"conversation_id": conversation_id},
            "UpdateExpression": expression,
            "ConditionExpression": "attribute_exists(conversation_id)",
            "ExpressionAttributeValues": {
                ":one": 1,
                ":at": message.created_at,
                ":preview": (message.content or "")[:_PREVIEW_CHARS],
            },
        }
    }


def save_message_idempotent(message: Message, *, count_as_unread: bool) -> tuple[Message, bool]:
    """Guarda un mensaje una sola vez por `client_message_id` (RF-038 / RNF-004).

    Sirve para el usuario (widget) y para el asesor (app): los dos reintentan con el mismo id.
    Devuelve `(mensaje, True)` si se guardo ahora y `(mensaje original, False)` si era un
    reintento: el frontend recibe en ambos casos el mismo mensaje confirmado (AC-006).
    """
    if not message.client_message_id:
        raise ValueError("un mensaje idempotente necesita client_message_id")
    table_messages = get_settings().table_messages
    marker = {
        "conversation_id": message.conversation_id,
        "message_key": idempotency_key_for(message.client_message_id),
        "target_message_key": message.message_key,
        "created_at": message.created_at,
    }
    # El client del resource serializa tipos Python (a diferencia de boto3.client puro).
    client = dynamodb_resource().meta.client
    try:
        client.transact_write_items(
            TransactItems=[
                {
                    "Put": {
                        "TableName": table_messages,
                        "Item": marker,
                        "ConditionExpression": "attribute_not_exists(message_key)",
                    }
                },
                {"Put": {"TableName": table_messages, "Item": message.to_item()}},
                _touch_conversation_update(
                    message.conversation_id, message, count_as_unread=count_as_unread
                ),
            ]
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "TransactionCanceledException":
            raise
        reasons = [r.get("Code") for r in exc.response.get("CancellationReasons", [])]
        if reasons and reasons[0] == "ConditionalCheckFailed":
            original = find_message_by_client_id(
                message.conversation_id, message.client_message_id
            )
            if original is not None:
                return original, False
        if len(reasons) > 2 and reasons[2] == "ConditionalCheckFailed":
            raise ConversationNotFound(message.conversation_id) from exc
        raise
    return message, True


def put_message(message: Message, *, count_as_unread: bool = False) -> None:
    """Guarda un mensaje saliente (BOT/ADVISOR/SYSTEM) y actualiza la conversacion, atomico."""
    client = dynamodb_resource().meta.client
    try:
        client.transact_write_items(
            TransactItems=[
                {"Put": {"TableName": get_settings().table_messages, "Item": message.to_item()}},
                _touch_conversation_update(
                    message.conversation_id, message, count_as_unread=count_as_unread
                ),
            ]
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "TransactionCanceledException":
            raise ConversationNotFound(message.conversation_id) from exc
        raise


def update_message_status(conversation_id: str, message_key: str, status: MessageStatus) -> None:
    _messages().update_item(
        Key={"conversation_id": conversation_id, "message_key": message_key},
        UpdateExpression="SET #status = :status",
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={":status": str(status)},
    )


def is_idempotency_marker(item: dict[str, Any]) -> bool:
    return str(item.get("message_key", "")).startswith(IDEMPOTENCY_KEY_PREFIX)
