"""Fixtures compartidas: entorno DynamoDB local con las tablas creadas y datos de prueba.

Las pruebas corren contra dynamodb-local REAL (no mocks de boto3), para que las claves y los
GSIs se validen de verdad — es la regla de la skill `testing`.
"""

import os
import uuid

import boto3
import pytest
from botocore.exceptions import BotoCoreError, ClientError

from backend.core.aws import reset_clients
from backend.core.config import reset_settings
from scripts.local_setup import cliente_dynamo, crear_tablas, nombres_de_tabla, recurso_dynamo
from scripts.seed_data import cargar


@pytest.fixture(scope="session", autouse=True)
def secretos_de_prueba():
    """Secretos de identidad (D-001) para toda la sesion de tests.

    En local suelen venir de `.env`; en CI no existe ese archivo y sin ellos cualquier request
    al chat responde 503. Se fijan con `setdefault` para respetar los que ya esten y se limpia
    la memoria de Settings, que pudo cargarse al importar `backend.api.main` en la coleccion.
    """
    os.environ.setdefault("VMC_IDENTITY_SECRET", "test-vmc-identity-secret")
    os.environ.setdefault("SESSION_SIGNING_KEY", "test-session-signing-key")
    reset_settings()
    reset_clients()


def _dynamo_disponible() -> bool:
    try:
        cliente = boto3.client(
            "dynamodb",
            endpoint_url=os.environ.get("DYNAMODB_ENDPOINT_URL", "http://localhost:8001"),
            region_name=os.environ.get("AWS_REGION", "us-east-1"),
            aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID", "local"),
            aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", "local"),
        )
        cliente.list_tables()
        return True
    except (ClientError, BotoCoreError, OSError):
        return False


@pytest.fixture(scope="session")
def entorno_dynamo():
    """Crea las tablas y carga los datos de prueba una vez por sesion.

    Si dynamodb-local no responde, se saltan las pruebas que dependen de el — EXCEPTO en CI,
    donde el servicio siempre existe y saltarlas ocultaria una regresion.
    """
    if not _dynamo_disponible():
        if os.environ.get("CI"):
            pytest.fail(
                "dynamodb-local no responde en CI. Revisar el bloque `services` de ci.yml."
            )
        pytest.skip("dynamodb-local no esta arriba — levantarlo con: docker compose up -d")

    crear_tablas(verbose=False)
    _purgar_restos_de_pruebas()
    cargar(verbose=False)
    return nombres_de_tabla()


def _purgar_restos_de_pruebas() -> None:
    """Borra items `conv_test_*` que hayan quedado de una corrida interrumpida.

    Sin esto, una conversacion de prueba abandonada aparece en los GSIs y rompe las
    aserciones de las consultas de lectura.
    """
    dynamo = recurso_dynamo()
    nombres = nombres_de_tabla()
    conversaciones = dynamo.Table(nombres["conversations"])
    for item in conversaciones.scan().get("Items", []):
        if item["conversation_id"].startswith("conv_test_"):
            conversaciones.delete_item(Key={"conversation_id": item["conversation_id"]})


@pytest.fixture
def conversacion_temporal(tablas):
    """Id unico para pruebas de escritura; borra la conversacion al terminar.

    Las pruebas que escriben NUNCA deben tocar entidades del dataset base (ni sus asesores),
    porque contaminarian las consultas de lectura de otras pruebas.
    """
    creadas: list[str] = []

    def nueva() -> str:
        conv_id = f"conv_test_{uuid.uuid4().hex[:8]}"
        creadas.append(conv_id)
        return conv_id

    yield nueva

    for conv_id in creadas:
        tablas["conversations"].delete_item(Key={"conversation_id": conv_id})


@pytest.fixture(scope="session")
def cliente_bajo_nivel(entorno_dynamo):
    """Cliente boto3 crudo, para operaciones que exigen el formato `{"S": ...}`.

    El cliente que cuelga de un Table (`.meta.client`) lleva un serializador que convierte
    tipos Python automaticamente: pasarle AttributeValues ya formateados los convertiria dos
    veces y DynamoDB responde ValidationException.
    """
    return cliente_dynamo()


@pytest.fixture(scope="session")
def tablas(entorno_dynamo):
    """Objetos Table de boto3, listos para consultar, indexados por nombre logico."""
    dynamo = recurso_dynamo()
    return {logico: dynamo.Table(fisico) for logico, fisico in entorno_dynamo.items()}
