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
    llamador quien decide como marcarlo (MessageStatus.QUEUE_FAILED).

    `DelaySeconds` es el debounce de D-020 (patron de SQS message timers): el job no se hace
    visible hasta pasados N segundos, y al procesarlo el worker responde solo si su mensaje
    sigue siendo el ultimo del usuario — asi una rafaga de frases partidas paga UNA llamada IA.
    """
    settings = get_settings()
    if not settings.ai_jobs_queue_url:
        raise QueueNotConfigured("Falta AI_JOBS_QUEUE_URL")
    sqs_client().send_message(
        QueueUrl=settings.ai_jobs_queue_url,
        MessageBody=job.model_dump_json(),
        DelaySeconds=max(0, min(settings.ai_debounce_seconds, 900)),  # tope de SQS: 15 min
    )
