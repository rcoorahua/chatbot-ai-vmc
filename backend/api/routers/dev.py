"""Rutas de observabilidad para dev y stage (`/dev/*`). NUNCA en prod.

    GET /dev/conversations/{id}/ai-usage   → ejecuciones del pipeline IA de la conversacion
                                             (tabla AIUsage) con totales de tokens y costo

Alimenta la consola de `widget/test.html`: que decidio el bot con cada mensaje (trivial, guardrail,
regla o modelo), que modelo llamo, cuantos tokens gasto, cuanto costo y cuanto tardo.

Gate: `DEV_OBSERVABILITY` (por defecto encendido salvo en prod). Apagado responde 404, no 403,
para no revelar que la ruta existe. Exige el MISMO token de sesion que `/chat` y solo muestra la
conversacion propia (D-002): en stage lo puede usar cualquiera con el widget, pero solo ve lo suyo
y nunca contenido de mensajes, solo metricas.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from backend.agent import usage
from backend.conversations import repository
from backend.core import auth, jobs
from backend.core.aws import dynamodb_resource, sqs_client
from backend.core.config import get_settings
from backend.core.dynamo_model import from_dynamo

router = APIRouter(prefix="/dev", tags=["dev"])


def _enabled() -> None:
    if not get_settings().dev_observability_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")


class RagFragmentOut(BaseModel):
    """Un fragmento que el RAG trajo para la pregunta. Nunca el texto del fragmento (regla del
    endpoint: solo metricas) — solo lo que sirve para juzgar si la recuperacion fue relevante.

    `relevant=False` marca un hit por debajo de RAG_MIN_SCORE: no fue evidencia, pero se
    muestra igual para juzgar el retrieval cuando la respuesta cayo en "sin evidencia".
    Filas anteriores a este campo no lo traen: se asumen relevantes (solo se guardaban esos)."""

    topic: str
    score: float
    source_url: str = ""
    relevant: bool = True


class ExecutionOut(BaseModel):
    execution_id: str
    execution_type: str
    message_id: str | None = None
    intent: str | None = None
    source: str
    provider: str
    model: str | None = None
    status: str
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    estimated_cost_usd: float = 0.0
    latency_ms: int = 0
    rag_used: bool = False
    rag_results_count: int | None = None
    rag_fragments: list[RagFragmentOut] = []
    rag_min_score: float | None = None
    handoff_triggered: bool = False
    created_at: str


class ConversationState(BaseModel):
    conversation_id: str
    status: str
    bot_enabled: bool
    wait_message_sent: bool
    handoff_reason: str | None = None
    message_count: int


class Totals(BaseModel):
    executions: int
    ai_calls: int
    free_executions: int
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    estimated_cost_usd: float
    total_latency_ms: int


class AIUsageOut(BaseModel):
    conversation: ConversationState
    executions: list[ExecutionOut]
    totals: Totals


@router.get(
    "/conversations/{conversation_id}/ai-usage",
    response_model=AIUsageOut,
    dependencies=[Depends(_enabled)],
)
def ai_usage(
    conversation_id: str,
    session: auth.CurrentSession,
    limit: int = Query(default=100, ge=1, le=500),
) -> AIUsageOut:
    if conversation_id != session.conversation_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Esta conversacion no es de tu sesion")
    conversation = repository.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversacion no encontrada")

    executions = [ExecutionOut(**item) for item in usage.list_executions(conversation_id, limit)]
    ai_calls = [e for e in executions if e.provider != usage.NO_PROVIDER]
    return AIUsageOut(
        conversation=ConversationState(
            conversation_id=conversation.conversation_id,
            status=str(conversation.status),
            bot_enabled=conversation.bot_enabled,
            wait_message_sent=conversation.wait_message_sent,
            handoff_reason=conversation.handoff_reason,
            message_count=conversation.message_count,
        ),
        executions=executions,
        totals=Totals(
            executions=len(executions),
            ai_calls=len(ai_calls),
            free_executions=len(executions) - len(ai_calls),
            input_tokens=sum(e.input_tokens for e in executions),
            output_tokens=sum(e.output_tokens for e in executions),
            cached_tokens=sum(e.cached_tokens for e in executions),
            estimated_cost_usd=round(sum(e.estimated_cost_usd for e in executions), 6),
            total_latency_ms=sum(e.latency_ms for e in executions),
        ),
    )


# ────────────────────── Inspector de tablas y colas (SOLO dev local) ──────────────────────
# Alimenta las pestañas "Tablas" y "Cola" de widget/test.html: ver como se apila un mensaje en
# DynamoDB y que viaja por SQS mientras se prueba a mano.
#
# Gate MAS estricto que el resto de /dev, a proposito: `ai-usage` muestra solo metricas de la
# conversacion propia y puede vivir en stage, pero un scan vuelca los mensajes de TODOS los
# usuarios — fuera de dev estas rutas no existen (404), ni siquiera en stage.

_TABLE_KEYS = ("conversations", "messages", "tickets", "advisors", "ai-usage")


def _solo_dev() -> None:
    settings = get_settings()
    if settings.stage != "dev" or not settings.dev_observability_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")


def _physical_name(key: str) -> str:
    settings = get_settings()
    names = {
        "conversations": settings.table_conversations,
        "messages": settings.table_messages,
        "tickets": settings.table_tickets,
        "advisors": settings.table_advisors,
        "ai-usage": settings.table_ai_usage,
    }
    if key not in names:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Tabla desconocida: {key}")
    return names[key]


@router.get("/tables", dependencies=[Depends(_solo_dev)])
def list_tables() -> dict[str, Any]:
    """Las cinco tablas con su conteo real (scan COUNT: en dev son diminutas)."""
    resource = dynamodb_resource()
    tables = []
    for key in _TABLE_KEYS:
        name = _physical_name(key)
        try:
            count = resource.Table(name).scan(Select="COUNT")["Count"]
        except Exception as error:  # noqa: BLE001 — contenedor apagado != 500 en la consola
            tables.append({"key": key, "name": name, "error": type(error).__name__})
            continue
        tables.append({"key": key, "name": name, "count": count})
    return {"tables": tables}


@router.get("/tables/{table_key}", dependencies=[Depends(_solo_dev)])
def scan_table(
    table_key: str, limit: int = Query(default=200, ge=1, le=500)
) -> dict[str, Any]:
    """Scan de una tabla para la consola. Un scan esta PROHIBIDO en codigo de producto (los
    repositorios usan query por clave/indice, y los tests lo verifican) — aqui es exactamente
    lo que se quiere: el volcado completo de una tabla chiquita de dev."""
    table = dynamodb_resource().Table(_physical_name(table_key))
    response = table.scan(Limit=limit)
    items = [from_dynamo(item) for item in response.get("Items", [])]
    return {
        "key": table_key,
        "name": table.name,
        # Las claves primero, para que la consola pinte esas columnas al inicio.
        "key_attributes": [k["AttributeName"] for k in table.key_schema],
        "count": len(items),
        "truncated": "LastEvaluatedKey" in response,
        "items": items,
    }


@router.get("/queues", dependencies=[Depends(_solo_dev)])
def inspect_queues() -> dict[str, Any]:
    """Estado de las colas + los cuerpos visibles + los ultimos encolados.

    SQS no tiene "peek": se hace receive con VisibilityTimeout=0, que devuelve el mensaje y lo
    deja visible al instante — el worker no pierde nada. Ojo: un job en pleno DelaySeconds (el
    debounce de D-020) no es visible ni para esto; para eso esta `recent_jobs`, capturado al
    encolar (core/jobs.py), que es el rastro fiel de lo que la API mando.
    """
    settings = get_settings()
    sqs = sqs_client()
    queues = []
    for key, url in (
        ("ai-jobs", settings.ai_jobs_queue_url),
        ("notifications", settings.notifications_queue_url),
    ):
        if not url:
            queues.append({"key": key, "error": "sin URL configurada"})
            continue
        try:
            attrs = sqs.get_queue_attributes(
                QueueUrl=url,
                AttributeNames=[
                    "ApproximateNumberOfMessages",
                    "ApproximateNumberOfMessagesNotVisible",
                    "ApproximateNumberOfMessagesDelayed",
                ],
            )["Attributes"]
            peek = sqs.receive_message(
                QueueUrl=url,
                MaxNumberOfMessages=10,
                WaitTimeSeconds=0,
                VisibilityTimeout=0,
                AttributeNames=["SentTimestamp"],
            ).get("Messages", [])
        except Exception as error:  # noqa: BLE001 — localstack apagado != 500 en la consola
            queues.append({"key": key, "error": type(error).__name__})
            continue
        queues.append(
            {
                "key": key,
                "visible": int(attrs.get("ApproximateNumberOfMessages", 0)),
                "in_flight": int(attrs.get("ApproximateNumberOfMessagesNotVisible", 0)),
                "delayed": int(attrs.get("ApproximateNumberOfMessagesDelayed", 0)),
                "peek": [
                    {
                        "message_id": m.get("MessageId"),
                        "body": m.get("Body"),
                        "sent_at_ms": int(m.get("Attributes", {}).get("SentTimestamp", 0)),
                    }
                    for m in peek
                ],
            }
        )
    return {"queues": queues, "recent_jobs": list(jobs.RECENT_JOBS)}
