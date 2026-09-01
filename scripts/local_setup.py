"""Crea los recursos AWS del entorno de desarrollo local (dynamodb-local + localstack).

Uso:
    docker compose up -d
    python -m scripts.local_setup

Es IDEMPOTENTE: se puede correr las veces que haga falta. Necesario tras cada reinicio de los
contenedores, porque dynamodb-local corre con -inMemory y pierde las tablas.

Las definiciones de tabla son ESPEJO de infra/stacks/subastin_stack.py (claves y GSIs del
modelo de PLAN.md §4). Si cambia una clave o un indice alla, hay que cambiarlo aqui.
"""

import os

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

# Timeout corto: si los contenedores no estan arriba, queremos fallar rapido y no colgarnos.
_CFG = Config(connect_timeout=3, read_timeout=5, retries={"max_attempts": 1})

STRING = "S"


def _env(nombre: str, defecto: str) -> str:
    return os.environ.get(nombre) or defecto


def nombres_de_tabla() -> dict[str, str]:
    """Nombres fisicos, configurables por entorno (mismos nombres de variable que usa CDK)."""
    return {
        "conversations": _env("TABLE_CONVERSATIONS", "subastin-dev-conversations"),
        "messages": _env("TABLE_MESSAGES", "subastin-dev-messages"),
        "tickets": _env("TABLE_TICKETS", "subastin-dev-tickets"),
        "advisors": _env("TABLE_ADVISORS", "subastin-dev-advisors"),
        "ai_usage": _env("TABLE_AI_USAGE", "subastin-dev-ai-usage"),
    }


def _gsi(nombre: str, pk: str, sk: str | None = None) -> dict:
    claves = [{"AttributeName": pk, "KeyType": "HASH"}]
    if sk:
        claves.append({"AttributeName": sk, "KeyType": "RANGE"})
    return {
        "IndexName": nombre,
        "KeySchema": claves,
        "Projection": {"ProjectionType": "ALL"},
    }


def definiciones_de_tabla() -> list[dict]:
    """Las 5 tablas del modelo (PLAN.md §4), con sus claves e indices."""
    t = nombres_de_tabla()
    return [
        {
            "TableName": t["conversations"],
            "KeySchema": [{"AttributeName": "conversation_id", "KeyType": "HASH"}],
            "AttributeDefinitions": [
                {"AttributeName": "conversation_id", "AttributeType": STRING},
                {"AttributeName": "user_id", "AttributeType": STRING},
                {"AttributeName": "status", "AttributeType": STRING},
                {"AttributeName": "assigned_advisor_id", "AttributeType": STRING},
                {"AttributeName": "updated_at", "AttributeType": STRING},
                {"AttributeName": "last_message_at", "AttributeType": STRING},
            ],
            "GlobalSecondaryIndexes": [
                _gsi("gsi1_user", "user_id", "updated_at"),
                _gsi("gsi2_inbox", "status", "last_message_at"),
                _gsi("gsi3_advisor", "assigned_advisor_id", "updated_at"),
            ],
        },
        {
            # SK = "<created_at ISO-8601>#<message_id>" → orden cronologico gratis (PLAN.md §4)
            "TableName": t["messages"],
            "KeySchema": [
                {"AttributeName": "conversation_id", "KeyType": "HASH"},
                {"AttributeName": "message_key", "KeyType": "RANGE"},
            ],
            "AttributeDefinitions": [
                {"AttributeName": "conversation_id", "AttributeType": STRING},
                {"AttributeName": "message_key", "AttributeType": STRING},
            ],
        },
        {
            "TableName": t["tickets"],
            "KeySchema": [{"AttributeName": "ticket_id", "KeyType": "HASH"}],
            "AttributeDefinitions": [
                {"AttributeName": "ticket_id", "AttributeType": STRING},
                {"AttributeName": "conversation_id", "AttributeType": STRING},
                {"AttributeName": "assigned_advisor_id", "AttributeType": STRING},
                {"AttributeName": "status", "AttributeType": STRING},
                {"AttributeName": "created_at", "AttributeType": STRING},
                {"AttributeName": "updated_at", "AttributeType": STRING},
            ],
            "GlobalSecondaryIndexes": [
                _gsi("gsi1_conversation", "conversation_id", "created_at"),
                _gsi("gsi2_advisor", "assigned_advisor_id", "updated_at"),
                _gsi("gsi3_status", "status", "created_at"),
            ],
        },
        {
            "TableName": t["advisors"],
            "KeySchema": [{"AttributeName": "advisor_id", "KeyType": "HASH"}],
            "AttributeDefinitions": [
                {"AttributeName": "advisor_id", "AttributeType": STRING},
                {"AttributeName": "cognito_sub", "AttributeType": STRING},
            ],
            # Sin SK: el sub de Cognito identifica a un unico asesor (PLAN.md §4)
            "GlobalSecondaryIndexes": [_gsi("gsi_cognito", "cognito_sub")],
        },
        {
            "TableName": t["ai_usage"],
            "KeySchema": [
                {"AttributeName": "conversation_id", "KeyType": "HASH"},
                {"AttributeName": "execution_key", "KeyType": "RANGE"},
            ],
            "AttributeDefinitions": [
                {"AttributeName": "conversation_id", "AttributeType": STRING},
                {"AttributeName": "execution_key", "AttributeType": STRING},
                {"AttributeName": "billing_month", "AttributeType": STRING},
                {"AttributeName": "created_at", "AttributeType": STRING},
            ],
            "GlobalSecondaryIndexes": [_gsi("gsi_billing", "billing_month", "created_at")],
        },
    ]


def cliente_dynamo():
    return boto3.client(
        "dynamodb",
        endpoint_url=_env("DYNAMODB_ENDPOINT_URL", "http://localhost:8001"),
        region_name=_env("AWS_REGION", "us-east-1"),
        aws_access_key_id=_env("AWS_ACCESS_KEY_ID", "local"),
        aws_secret_access_key=_env("AWS_SECRET_ACCESS_KEY", "local"),
        config=_CFG,
    )


def recurso_dynamo():
    return boto3.resource(
        "dynamodb",
        endpoint_url=_env("DYNAMODB_ENDPOINT_URL", "http://localhost:8001"),
        region_name=_env("AWS_REGION", "us-east-1"),
        aws_access_key_id=_env("AWS_ACCESS_KEY_ID", "local"),
        aws_secret_access_key=_env("AWS_SECRET_ACCESS_KEY", "local"),
        config=_CFG,
    )


def crear_tablas(verbose: bool = True) -> None:
    """Crea las 5 tablas si no existen. Ignora las que ya estan."""
    cliente = cliente_dynamo()
    for definicion in definiciones_de_tabla():
        nombre = definicion["TableName"]
        try:
            cliente.create_table(BillingMode="PAY_PER_REQUEST", **definicion)
            cliente.get_waiter("table_exists").wait(TableName=nombre)
            if verbose:
                print(f"  tabla creada: {nombre}")
        except ClientError as e:
            if e.response["Error"]["Code"] == "ResourceInUseException":
                if verbose:
                    print(f"  tabla ya existia: {nombre}")
            else:
                raise


def cliente_sqs():
    return boto3.client(
        "sqs",
        endpoint_url=_env("SQS_ENDPOINT_URL", "http://localhost:4566"),
        region_name=_env("AWS_REGION", "us-east-1"),
        aws_access_key_id=_env("AWS_ACCESS_KEY_ID", "local"),
        aws_secret_access_key=_env("AWS_SECRET_ACCESS_KEY", "local"),
        config=_CFG,
    )


def nombres_de_cola() -> tuple[str, str]:
    """(ai-jobs, notifications). Reusado por reset_local.py para purgar sin duplicar los ids."""
    return ("subastin-dev-ai-jobs", "subastin-dev-notifications")


def crear_colas_y_bucket(verbose: bool = True) -> None:
    """SQS y S3 en LocalStack. No bloquea si LocalStack no esta arriba (es opcional para tests)."""
    comunes = {
        "region_name": _env("AWS_REGION", "us-east-1"),
        "aws_access_key_id": _env("AWS_ACCESS_KEY_ID", "local"),
        "aws_secret_access_key": _env("AWS_SECRET_ACCESS_KEY", "local"),
        "config": _CFG,
    }
    endpoint = _env("SQS_ENDPOINT_URL", "http://localhost:4566")
    try:
        sqs = cliente_sqs()
        for cola in nombres_de_cola():
            sqs.create_queue(QueueName=cola)
            if verbose:
                print(f"  cola lista: {cola}")

        s3 = boto3.client("s3", endpoint_url=_env("S3_ENDPOINT_URL", endpoint), **comunes)
        bucket = _env("IMAGES_BUCKET", "subastin-dev-images")
        try:
            s3.create_bucket(Bucket=bucket)
        except ClientError as e:
            ya_existe = ("BucketAlreadyOwnedByYou", "BucketAlreadyExists")
            if e.response["Error"]["Code"] not in ya_existe:
                raise
        if verbose:
            print(f"  bucket listo: {bucket}")
    except Exception as e:  # noqa: BLE001 — LocalStack es opcional para las pruebas de Dynamo
        if verbose:
            print(f"  AVISO: LocalStack no disponible ({type(e).__name__}); se omiten SQS y S3")


def main() -> None:
    print("Creando recursos locales...")
    crear_tablas()
    crear_colas_y_bucket()
    print("Listo. Datos de prueba: python -m scripts.seed_data")


if __name__ == "__main__":
    main()
