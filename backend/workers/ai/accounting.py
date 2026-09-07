"""Contabilidad del pipeline en AIUsage (T-04, skill llm-cost-optimizer): TODA decision
queda registrada, tambien las gratuitas — la proporcion de trafico que no paga tokens es la
metrica que justifica D-006 y las reglas.

El costo se calcula con el precio del modelo que REALMENTE respondio (`llm.cost_for`): el
respaldo del tier tiene otra tarifa y cobrarlo con la del principal subestima.
"""

from backend.agent import usage
from backend.agent.classifier import ClassificationResult
from backend.agent.intents import Intent
from backend.agent.rag import RagResult
from backend.agent.writer import WriterResult
from backend.conversations.models import Conversation, Message
from backend.core import llm
from backend.workers.ai.trace import ctx, logger

# Proveedor que AIUsage registra cuando un tier de Gemini atendio la llamada.
GOOGLE = "GOOGLE"


def record_classification(
    conversation: Conversation, message: Message, classification: ClassificationResult
) -> None:
    called_model = classification.source == "model"
    if classification.error:
        # El clasificador no lo loguea (es hoja): aqui, con la conversacion, queda el rastro.
        logger.warning(
            "ai.classifier.llm_error",
            extra=ctx(conversation, message, error=classification.error),
        )
    usage.record_execution(
        conversation_id=conversation.conversation_id,
        message_id=message.message_id,
        execution_type=usage.CLASSIFICATION,
        intent=str(classification.intent),
        source=classification.rule or classification.source,
        provider=GOOGLE if called_model else usage.NO_PROVIDER,
        model=classification.model,
        usage=classification.usage,
        estimated_cost_usd=llm.cost_for(
            classification.model, classification.usage, tier=llm.ModelTier.FAST
        ),
        latency_ms=classification.latency_ms,
        status=usage.ERROR if classification.error else usage.SUCCESS,
        error=classification.error,
    )


def record_answer(
    conversation: Conversation,
    message: Message,
    *,
    result: WriterResult,
    retrieved: RagResult,
    source: str,
) -> None:
    """La respuesta FAQ: modelo, tokens, costo y — para la consola de dev — TODOS los hits del
    indice, tambien los que no superaron el umbral: cuando la respuesta cae en "sin
    evidencia", hay que ver que trajo el indice y con que score para juzgar el retrieval (y el
    umbral) sin reproducir la consulta a mano."""
    fragments = retrieved.relevant
    usage.record_execution(
        conversation_id=conversation.conversation_id,
        message_id=message.message_id,
        execution_type=usage.RESPONSE,
        intent=str(Intent.FAQ),
        source=source,
        provider=GOOGLE if result.model else usage.NO_PROVIDER,
        model=result.model,
        usage=result.usage,
        estimated_cost_usd=llm.cost_for(result.model, result.usage, tier=llm.ModelTier.ANSWER),
        latency_ms=result.latency_ms,
        rag_used=bool(fragments),
        rag_results_count=len(fragments),
        rag_fragments=[
            {
                "topic": f.topic,
                "score": f.score,
                "source_url": f.source_url,
                "relevant": f in retrieved.relevant,
                "sibling": f.sibling,
            }
            for f in retrieved.all_fragments
        ],
        rag_min_score=retrieved.threshold,
        handoff_triggered=not result.has_evidence,
        status=usage.ERROR if result.error else usage.SUCCESS,
        error=result.error,
    )


def record_free(
    conversation: Conversation,
    message: Message,
    *,
    source: str,
    intent: Intent | str | None = None,
    handoff: bool = False,
) -> None:
    """Registra una decision que no pago tokens — la metrica que justifica D-006 y las reglas."""
    usage.record_execution(
        conversation_id=conversation.conversation_id,
        message_id=message.message_id,
        execution_type=usage.RESPONSE,
        intent=str(intent) if intent else None,
        source=source,
        provider=usage.NO_PROVIDER,
        model=None,
        usage=None,
        estimated_cost_usd=0.0,
        latency_ms=0,
        handoff_triggered=handoff,
    )
