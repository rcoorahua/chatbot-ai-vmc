"""Corre el worker de IA en LOCAL contra la cola de localstack, para que el bot responda en el
widget de dev.

    python -m scripts.run_ai_worker

Requiere docker-compose arriba, `python -m scripts.local_setup` ejecutado y `GEMINI_API_KEY`
en `.env` (y `PINECONE_API_KEY` si quieres respuestas FAQ con evidencia; sin ella el RAG
devuelve vacio y el bot deriva, que es el comportamiento de RF-018, no un error).

En AWS este proceso no existe: SQS invoca la Lambda `worker-ai` directamente. Aqui se emula ese
contrato — se recibe el batch, se construye el MISMO event que arma Lambda y se respeta
`batchItemFailures`: los jobs fallidos NO se borran de la cola y reaparecen tras el visibility
timeout, igual que en produccion.
"""

from __future__ import annotations

import time

from backend.core.aws import sqs_client
from backend.core.config import get_settings
from backend.workers.ai_worker import handler


def main() -> None:
    settings = get_settings()
    if not settings.ai_jobs_queue_url:
        raise SystemExit("Falta AI_JOBS_QUEUE_URL en .env (correr scripts.local_setup)")
    print(f"Escuchando {settings.ai_jobs_queue_url} — Ctrl+C para salir")

    sqs = sqs_client()
    while True:
        try:
            response = sqs.receive_message(
                QueueUrl=settings.ai_jobs_queue_url,
                MaxNumberOfMessages=10,
                WaitTimeSeconds=10,  # long polling: sin busy-wait entre mensajes
            )
        except KeyboardInterrupt:
            raise
        except Exception as error:  # noqa: BLE001 — localstack reiniciandose no debe matar el loop
            print(f"SQS no responde ({error}); reintento en 3 s")
            time.sleep(3)
            continue

        records = response.get("Messages", [])
        if not records:
            continue

        event = {
            "Records": [
                {"messageId": item["MessageId"], "body": item["Body"]} for item in records
            ]
        }
        result = handler(event, None)
        failed = {failure["itemIdentifier"] for failure in result["batchItemFailures"]}

        for item in records:
            if item["MessageId"] in failed:
                print(f"  job {item['MessageId'][:8]} fallo — vuelve a la cola")
                continue
            sqs.delete_message(
                QueueUrl=settings.ai_jobs_queue_url, ReceiptHandle=item["ReceiptHandle"]
            )
            print(f"  job {item['MessageId'][:8]} atendido")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nListo.")
