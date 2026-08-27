"""Contrato del job de IA entre la API (productor, T8) y `worker-ai` (consumidor, T3).

Vive en core porque lo comparten dos entradas (api/ y workers/) y ninguna debe importar a la
otra. El body de SQS se trata como no confiable en el worker: se valida con este mismo modelo
antes de usarlo (regla 6 de la skill security-guidance).
"""

from pydantic import BaseModel

from backend.core.aws import sqs_client
from backend.core.config import get_settings


class AIJob(BaseModel):
    conversation_id: str
    message_id: str
    message_key: str
    requested_at: str


class QueueNotConfigured(RuntimeError):
    pass


def enqueue_ai_job(job: AIJob) -> None:
    """Encola y vuelve. Cualquier fallo sube al llamador: el mensaje ya es durable y es el
    llamador quien decide como marcarlo (MessageStatus.QUEUE_FAILED)."""
    queue_url = get_settings().ai_jobs_queue_url
    if not queue_url:
        raise QueueNotConfigured("Falta AI_JOBS_QUEUE_URL")
    sqs_client().send_message(QueueUrl=queue_url, MessageBody=job.model_dump_json())
