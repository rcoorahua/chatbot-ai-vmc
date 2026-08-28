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

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from backend.agent import usage
from backend.conversations import repository
from backend.core import auth
from backend.core.config import get_settings

router = APIRouter(prefix="/dev", tags=["dev"])


def _enabled() -> None:
    if not get_settings().dev_observability_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")


class RagFragmentOut(BaseModel):
    """Un fragmento que el RAG trajo para la pregunta. Nunca el texto del fragmento (regla del
    endpoint: solo metricas) — solo lo que sirve para juzgar si la recuperacion fue relevante."""

    topic: str
    score: float
    source_url: str = ""


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
