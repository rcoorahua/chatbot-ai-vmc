"""UNICO lugar que conoce claves/GSIs de Conversations y Messages (PLAN.md §4).

Patrones que viven aqui y en ningun otro sitio:
- conversacion por id (PK) y por usuario (GSI1 `user_id`/`updated_at`);
- creacion condicional (`attribute_not_exists`) para que dos pestañas abiertas a la vez no
  creen dos conversaciones para el mismo usuario (D-002: maximo 1);
- guardado IDEMPOTENTE del mensaje entrante: una transaccion con item marcador
  `CMID#<client_message_id>` + el mensaje + los contadores de la conversacion (ajuste 4 de
  REQUERIMENTS.md §1.11, validado en tests/test_dynamo_queries.py);
- listado cronologico por SK y ventana reciente para la IA (RF-013), ambos dejando fuera los
  marcadores de idempotencia.

Los tests de este modulo corren contra dynamodb-local real: un GSI mal usado falla aqui.
"""

from typing import Any

from boto3.dynamodb.conditions import Key
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


def list_recent_messages(conversation_id: str, *, limit: int = 20) -> list[Message]:
    """Los ultimos N mensajes en orden natural: la ventana de contexto de la IA (RF-013).

    Se consulta descendente con Limit y se reinvierte. La cota superior de la SK importa aun
    mas aqui: en orden descendente los marcadores `CMID#` saldrian PRIMERO y se comerian el
    Limit, devolviendo una ventana llena de marcadores en vez de mensajes.
    """
    response = _messages().query(
        KeyConditionExpression=Key("conversation_id").eq(conversation_id)
        & Key("message_key").between(_FIRST_MESSAGE_KEY, _LAST_MESSAGE_KEY),
        ScanIndexForward=False,
        Limit=limit,
    )
    return [Message.from_item(item) for item in reversed(response["Items"])]


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


def save_user_message(message: Message, *, count_as_unread: bool) -> tuple[Message, bool]:
    """Guarda un mensaje entrante una sola vez por `client_message_id` (RF-038 / RNF-004).

    Devuelve `(mensaje, True)` si se guardo ahora y `(mensaje original, False)` si era un
    reintento: el frontend recibe en ambos casos el mismo mensaje confirmado (AC-006).
    """
    if not message.client_message_id:
        raise ValueError("un mensaje de usuario necesita client_message_id")
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
