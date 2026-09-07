"""Ayudas de DynamoDB que comparten todos los repositories.

Vive en `core` porque la regla de dependencias (backend/__init__.py) prohibe que un dominio
importe a otro, y cada repository (conversations, tickets, advisors, y las tablas de agent)
repetia estas mismas lineas. Aqui va SOLO lo que no sabe de ninguna tabla en particular:
claves, GSIs y condiciones siguen siendo de cada repository.
"""

from typing import Any

from botocore.exceptions import ClientError

CONDITION_FAILED = "ConditionalCheckFailedException"
TRANSACTION_CANCELED = "TransactionCanceledException"
CONDITION_FAILED_REASON = "ConditionalCheckFailed"


def is_condition_failure(exc: ClientError) -> bool:
    """La escritura condicional (put/update con ConditionExpression) no paso su condicion."""
    return exc.response["Error"]["Code"] == CONDITION_FAILED


def is_transaction_canceled(exc: ClientError) -> bool:
    return exc.response["Error"]["Code"] == TRANSACTION_CANCELED


def cancellation_reasons(exc: ClientError) -> list[str | None]:
    """Codigo de cancelacion de CADA item de una transaccion, en el orden de `TransactItems`
    (`None` para los que no fallaron). Solo tiene sentido tras `is_transaction_canceled`."""
    return [reason.get("Code") for reason in exc.response.get("CancellationReasons", [])]


def condition_failed_at(exc: ClientError, index: int) -> bool:
    """¿La transaccion se cancelo porque el item `index` no paso su condicion?"""
    reasons = cancellation_reasons(exc)
    return len(reasons) > index and reasons[index] == CONDITION_FAILED_REASON


def query_up_to(table: Any, wanted: int, **kwargs: Any) -> list[dict[str, Any]]:
    """`query` paginando hasta juntar `wanted` items o agotar el indice.

    Hace falta con `FilterExpression`: DynamoDB aplica `Limit` ANTES del filtro, asi que una
    sola pagina puede volver corta o vacia aunque haya items que pasan el filtro mas atras
    (auditoria 2026-09-06: los casos cerrados mas recientes tapaban a los abiertos en la
    bandeja del asesor). Sin filtro equivale a un `query` con `Limit=wanted`.
    """
    found: list[dict[str, Any]] = []
    start_key: dict[str, Any] | None = None
    while len(found) < wanted:
        if start_key:
            kwargs["ExclusiveStartKey"] = start_key
        response = table.query(Limit=wanted, **kwargs)
        found.extend(response["Items"])
        start_key = response.get("LastEvaluatedKey")
        if not start_key:
            break
    return found[:wanted]
