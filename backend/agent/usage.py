"""UNICO lugar que conoce claves/GSI de AIUsage (PK `conversation_id`, SK
`execution_key = created_at#execution_id`; GSI `gsi_billing` por `billing_month`/`created_at`).

Regla 1 de la skill llm-cost-optimizer: **toda** decision del pipeline registra aqui, tambien
las que no llamaron a ningun modelo (reglas, triviales, cortocircuitos) — con tokens y costo en
cero. Esa proporcion de trafico gratuito es justamente el dato que dice si las heuristicas y
D-006 valen lo que cuestan en mantenimiento. Se alimenta desde F2; NO se expone en el dashboard
del MVP (RF-049), pero los datos no se pueden reconstruir despues.

El costo va como Decimal: DynamoDB no acepta float, y en dinero la conversion binaria pierde
precision. Se serializa desde el string del float para no heredar sus digitos fantasma.
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal
from typing import Any

from backend.core.aws import dynamodb_resource
from backend.core.clock import utc_now_iso
from backend.core.config import get_settings

# Tipos de ejecucion (mismos valores que scripts/seed_data.py).
CLASSIFICATION = "CLASSIFICATION"
RESPONSE = "RESPONSE"

# Proveedor de los caminos que no llamaron a ningun modelo (reglas, triviales, fallbacks).
NO_PROVIDER = "NONE"

logger = logging.getLogger(__name__)

# Campos de la fila que NO van al log: la SK y el mes de facturacion son detalle de almacenamiento.
_NOT_LOGGED = frozenset({"execution_key", "billing_month"})


def _table():
    return dynamodb_resource().Table(get_settings().table_ai_usage)


def list_executions(conversation_id: str, limit: int = 100) -> list[dict[str, Any]]:
    """Ejecuciones de una conversacion, de la mas reciente a la mas antigua (consola de dev en
    `api/routers/dev.py` y auditoria). Devuelve dicts planos con numeros nativos: boto3 entrega
    Decimal y los modelos de salida quieren int/float."""
    from boto3.dynamodb.conditions import Key

    from backend.core.dynamo_model import from_dynamo

    response = _table().query(
        KeyConditionExpression=Key("conversation_id").eq(conversation_id),
        ScanIndexForward=False,
        Limit=limit,
    )
    return [from_dynamo(item) for item in response.get("Items", [])]


def record_execution(
    *,
    conversation_id: str,
    message_id: str,
    execution_type: str,
    intent: str | None,
    source: str,
    provider: str,
    model: str | None,
    usage: dict[str, int] | None,
    estimated_cost_usd: float,
    latency_ms: int,
    rag_used: bool = False,
    rag_results_count: int | None = None,
    rag_fragments: list[dict[str, Any]] | None = None,
    handoff_triggered: bool = False,
    status: str = "SUCCESS",
) -> None:
    """Registra una ejecucion del pipeline. Nunca lanza hacia el llamador: perder una metrica
    es malo, pero dejar al usuario sin respuesta porque fallo la contabilidad es peor — el
    worker ya respondio cuando esto corre."""
    created_at = utc_now_iso()
    execution_id = f"exec_{uuid.uuid4().hex[:12]}"
    tokens = usage or {}
    item: dict[str, Any] = {
        "conversation_id": conversation_id,
        "execution_key": f"{created_at}#{execution_id}",
        "execution_id": execution_id,
        "execution_type": execution_type,
        "message_id": message_id,
        "provider": provider,
        "status": status,
        "source": source,
        "billing_month": created_at[:7],  # "2026-08" — la clave del GSI de facturacion
        "created_at": created_at,
        "input_tokens": int(tokens.get("input", 0)),
        "output_tokens": int(tokens.get("output", 0)),
        "cached_tokens": int(tokens.get("cached_read", 0)),
        "estimated_cost_usd": Decimal(str(estimated_cost_usd)),
        "latency_ms": int(latency_ms),
        "rag_used": rag_used,
        "handoff_triggered": handoff_triggered,
    }
    if model:
        item["model"] = model
    if intent:
        item["intent"] = intent
    if rag_results_count is not None:
        item["rag_results_count"] = rag_results_count
    if rag_fragments:
        # Que trajo el RAG para esta respuesta (consola de dev, api/routers/dev.py): tema,
        # score y fuente de cada fragmento recuperado. NUNCA el texto del fragmento — eso es
        # contenido del Centro de Ayuda, no el mensaje del usuario, pero igual no hace falta
        # para depurar el retrieval y agrandaria la fila sin necesidad.
        item["rag_fragments"] = [
            {
                "topic": fragment["topic"],
                "score": Decimal(str(round(fragment["score"], 4))),
                "source_url": fragment["source_url"],
            }
            for fragment in rag_fragments
        ]
    # Un evento por ejecucion, con las mismas claves que la fila (RNF-006): en CloudWatch Logs
    # Insights `filter event = "ai.execution" | stats sum(estimated_cost_usd) by source` da la
    # foto de costos sin tocar DynamoDB. Sin contenido de mensajes: solo ids y metricas.
    logger.info(
        "ai.execution",
        extra={
            **{key: value for key, value in item.items() if key not in _NOT_LOGGED},
            "estimated_cost_usd": float(estimated_cost_usd),
        },
    )
    try:
        _table().put_item(Item=item)
    except Exception:  # noqa: BLE001 — ver docstring: la respuesta ya salio, esto no la anula
        logger.exception(
            "No se pudo registrar en AIUsage", extra={"conversation_id": conversation_id}
        )
