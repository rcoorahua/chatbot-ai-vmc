"""Escenario a nivel de dominio + worker, contra dynamodb-local real.

Lo que todas las pruebas del pipeline IA hacen: abrir una conversacion, escribir como el
usuario, atender el job como lo haria SQS y leer lo que respondio el bot. `limpiar` es la
fixture de `tests/conftest.py`: todo lo que se crea aqui se registra ahi para borrarse.
"""

import uuid

from boto3.dynamodb.conditions import Key

from backend.conversations import repository, service
from backend.conversations.models import Conversation, Message, SenderType
from backend.core.auth import VmcIdentity
from backend.core.jobs import AIJob
from backend.workers import ai_worker


def identidad(name: str = "Jorge", **extra) -> VmcIdentity:
    """Un usuario de VMC distinto por llamada: las conversaciones del autenticado tienen id
    determinista, asi que dos pruebas con el mismo user_id se pisarian."""
    return VmcIdentity(user_id="vmc_" + uuid.uuid4().hex[:8], name=name, **extra)


def conversacion(limpiar, *, autenticada: bool = True, name: str = "Jorge") -> Conversation:
    conversation, _ = service.open_conversation(identidad(name) if autenticada else None)
    limpiar(conversation.conversation_id)
    return conversation


def client_message_id() -> str:
    return "cli-" + uuid.uuid4().hex


def escribe(
    conversation: Conversation, texto: str, interaction: dict | None = None, *, metadata=None
) -> Message:
    """El usuario escribe (RF-038: cada mensaje con su client_message_id). `interaction` es el
    evento estructurado de un quick reply (D-028); viaja en `metadata.interaction`."""
    if interaction is not None:
        metadata = {"interaction": interaction}
    message, _ = service.post_user_message(
        conversation, client_message_id=client_message_id(), content=texto, metadata=metadata
    )
    return message


def escribe_interaccion(
    conversation: Conversation, texto: str, *, action_id: str, value: str, flow_version: int
) -> Message:
    """El clic de un quick reply: texto visible + el evento estructurado (MAPEO.md §3)."""
    return escribe(
        conversation,
        texto,
        {"action_id": action_id, "value": value, "flow_version": flow_version},
    )


def job(message: Message, *, ip_hash: str | None = None) -> str:
    """El cuerpo del job tal como lo encola la API (core/jobs.py)."""
    return AIJob(
        conversation_id=message.conversation_id,
        message_id=message.message_id,
        message_key=message.message_key,
        requested_at=message.created_at,
        ip_hash=ip_hash,
    ).model_dump_json()


def atiende(message: Message, *, ip_hash: str | None = None) -> None:
    """El worker procesa el job de ese mensaje, como lo haria al recibirlo de SQS."""
    ai_worker._process(job(message, ip_hash=ip_hash))


def hilo_de(conversation_id: str) -> list[Message]:
    return repository.list_messages(conversation_id)


def respuestas_bot(conversation_id: str) -> list[Message]:
    return [m for m in hilo_de(conversation_id) if m.sender_type == SenderType.BOT]


def ultima_respuesta(conversation_id: str) -> str | None:
    bots = respuestas_bot(conversation_id)
    return bots[-1].content if bots else None


def fresca(conversation: Conversation) -> Conversation:
    """La fila tal como esta en la tabla ahora (el worker la muta: flujo, version, estado)."""
    return repository.get_conversation(conversation.conversation_id)


def usos_de(tablas, conversation_id: str) -> list[dict]:
    """Filas de AIUsage de la conversacion, en orden cronologico."""
    return sorted(
        tablas["ai_usage"].query(
            KeyConditionExpression=Key("conversation_id").eq(conversation_id)
        )["Items"],
        key=lambda u: u["created_at"],
    )


def usos_del_mensaje(tablas, conversation_id: str, message_id: str) -> list[dict]:
    return [u for u in usos_de(tablas, conversation_id) if u.get("message_id") == message_id]
