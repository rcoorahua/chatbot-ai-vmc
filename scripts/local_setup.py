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
from botocore.exceptions import ClientError, ConnectTimeoutError, EndpointConnectionError

from backend.core.config import get_settings

# Timeout corto: si los contenedores no estan arriba, queremos fallar rapido y no colgarnos.
_CFG = Config(connect_timeout=3, read_timeout=5, retries={"max_attempts": 1})

STRING = "S"

# Tablas con TTL sobre `expires_at`, ESPEJO de infra/stacks/subastin_stack.py: la conversacion
# anonima y sus mensajes caducan solos (D-029/D-031) y los contadores de cuota a las 48 h
# (D-027). dynamodb-local tambien lo aplica; sin activarlo aqui, ese camino nunca se ejercitaba
# en dev (auditoria 2026-09-06).
TABLAS_CON_TTL = ("conversations", "messages", "rate_limits")
TTL_ATTRIBUTE = "expires_at"


def _env(nombre: str, defecto: str) -> str:
    """Variable de entorno, o el valor que `Settings` leyo de `.env`, o el default. Antes solo
    se miraba `os.environ` y un override en `.env` (que el backend SI honra) creaba las tablas
    con otro nombre del que la API consultaba."""
    if os.environ.get(nombre):
        return os.environ[nombre]
    de_settings = getattr(get_settings(), nombre.lower(), None)
    return str(de_settings) if de_settings else defecto


def nombres_de_tabla() -> dict[str, str]:
    """Nombres fisicos, configurables por entorno (mismos nombres de variable que usa CDK)."""
    return {
        "conversations": _env("TABLE_CONVERSATIONS", "subastin-dev-conversations"),
        "messages": _env("TABLE_MESSAGES", "subastin-dev-messages"),
        "tickets": _env("TABLE_TICKETS", "subastin-dev-tickets"),
        "advisors": _env("TABLE_ADVISORS", "subastin-dev-advisors"),
        "ai_usage": _env("TABLE_AI_USAGE", "subastin-dev-ai-usage"),
        "rate_limits": _env("TABLE_RATE_LIMITS", "subastin-dev-rate-limits"),
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
    """Las 6 tablas del modelo (PLAN.md §4 + RateLimits de T-09/D-027), con claves e indices."""
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
        {
            # T-09 / D-027: contadores del tope de ejecuciones de IA por actor. PK = quien
            # (`USER#<id>` / `SESSION#<conversation_id>` / `IP#<hash>`), SK = la ventana
            # (`H#2026-09-01T19` por hora, `D#2026-09-01` por dia). En AWS lleva TTL sobre
            # `expires_at` (48 h) para que DynamoDB borre solo; dynamodb-local es -inMemory
            # asi que aqui no hace falta activarlo.
            "TableName": t["rate_limits"],
            "KeySchema": [
                {"AttributeName": "limit_key", "KeyType": "HASH"},
                {"AttributeName": "window", "KeyType": "RANGE"},
            ],
            "AttributeDefinitions": [
                {"AttributeName": "limit_key", "AttributeType": STRING},
                {"AttributeName": "window", "AttributeType": STRING},
            ],
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
    """Crea las 6 tablas si no existen (ignora las que ya estan) y activa el TTL donde AWS lo
    tiene."""
    cliente = cliente_dynamo()
    nombres = nombres_de_tabla()
    con_ttl = {nombres[logico] for logico in TABLAS_CON_TTL}
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
        if nombre in con_ttl:
            _activar_ttl(cliente, nombre)


def _activar_ttl(cliente, nombre: str) -> None:
    """Idempotente: dynamodb-local responde ValidationException si ya estaba activo."""
    try:
        cliente.update_time_to_live(
            TableName=nombre,
            TimeToLiveSpecification={"Enabled": True, "AttributeName": TTL_ATTRIBUTE},
        )
    except ClientError as e:
        if e.response["Error"]["Code"] != "ValidationException":
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


# ESPEJO de infra/stacks/subastin_stack.py (regla cerrada: visibility >= 6x el timeout del
# worker: 120 s el de IA, 30 s el de notificaciones; infra/config.py). Con el default de SQS
# (30 s), un job de IA que tardara mas se reentregaba a medio procesar y el bot respondia DOS
# veces la misma pregunta (2026-09-08). tests/test_local_setup.py lo compara con infra/config.
VISIBILITY_TIMEOUT_S = {"subastin-dev-ai-jobs": 720, "subastin-dev-notifications": 180}


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
            # create_queue es idempotente pero NO cambia los atributos de una cola que ya
            # existe: se fijan aparte para que local_setup/reset_local repetidos converjan.
            # Con la URL del endpoint de .env y no la que devuelve LocalStack (exige DNS).
            sqs.set_queue_attributes(
                QueueUrl=f"{endpoint}/000000000000/{cola}",
                Attributes={"VisibilityTimeout": str(VISIBILITY_TIMEOUT_S[cola])},
            )
            if verbose:
                print(f"  cola lista: {cola}")
                if cola.endswith("ai-jobs"):
                    # Sin esta variable el mensaje queda QUEUE_FAILED y el bot nunca responde
                    # (CLAUDE.md "Comandos"): se imprime lista para pegar en .env. Con el
                    # endpoint de .env y no con la URL que devuelve LocalStack, que usa un
                    # hostname *.localhost.localstack.cloud que exige DNS de internet.
                    print(f"    -> en .env: AI_JOBS_QUEUE_URL={endpoint}/000000000000/{cola}")

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
    except (EndpointConnectionError, ConnectTimeoutError) as e:
        # LocalStack es opcional para las pruebas de Dynamo: solo "no responde" se tolera.
        # Cualquier OTRO error (permisos, nombre invalido) se propaga: antes se tragaba todo
        # y el sintoma aparecia despues, en run_ai_worker, con otro mensaje.
        if verbose:
            print(f"  AVISO: LocalStack no disponible ({type(e).__name__}); se omiten SQS y S3")


def main() -> None:
    print("Creando recursos locales...")
    crear_tablas()
    crear_colas_y_bucket()
    print("Listo. Datos de prueba: python -m scripts.seed_data")


if __name__ == "__main__":
    main()
