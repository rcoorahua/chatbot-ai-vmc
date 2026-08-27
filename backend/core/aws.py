"""Clients boto3 (DynamoDB, SQS) creados una vez por proceso y reusados entre invocaciones.

`endpoint_url` solo se pasa cuando Settings lo trae (dev local: dynamodb-local y localstack);
en AWS queda None y boto3 resuelve el endpoint y las credenciales del rol de ejecucion.
"""

import os
from functools import lru_cache
from typing import Any

import boto3
from botocore.config import Config

from backend.core.config import get_settings

# Timeouts cortos: una Lambda `api` tiene 15 s en total; esperar 60 s a un endpoint caido solo
# convierte un error claro en un timeout del gateway.
_BOTO_CONFIG = Config(connect_timeout=3, read_timeout=10, retries={"max_attempts": 2})


def _client_kwargs(endpoint_url: str | None) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"region_name": get_settings().aws_region, "config": _BOTO_CONFIG}
    if endpoint_url:
        kwargs["endpoint_url"] = endpoint_url
        # Modo local: dynamodb-local y localstack no validan credenciales, pero boto3 exige
        # alguna. Se pasan SOLO aqui: en Lambda las inyecta el rol (con session token) y
        # pasarlas a mano rompe la firma de las llamadas.
        kwargs["aws_access_key_id"] = os.environ.get("AWS_ACCESS_KEY_ID", "local")
        kwargs["aws_secret_access_key"] = os.environ.get("AWS_SECRET_ACCESS_KEY", "local")
    return kwargs


@lru_cache
def dynamodb_resource():
    return boto3.resource("dynamodb", **_client_kwargs(get_settings().dynamodb_endpoint_url))


@lru_cache
def sqs_client():
    return boto3.client("sqs", **_client_kwargs(get_settings().sqs_endpoint_url))


def reset_clients() -> None:
    """Descarta los clients memorizados. Para tests que cambian Settings."""
    dynamodb_resource.cache_clear()
    sqs_client.cache_clear()
