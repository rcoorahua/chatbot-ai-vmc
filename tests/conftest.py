"""Fixtures compartidas: entorno DynamoDB local con las tablas creadas y datos de prueba.

Las pruebas corren contra dynamodb-local REAL (no mocks de boto3), para que las claves y los
GSIs se validen de verdad — es la regla de la skill `testing`.
"""

import os
import uuid

import boto3
import pytest
from boto3.dynamodb.conditions import Key
from botocore.exceptions import BotoCoreError, ClientError
from fastapi.testclient import TestClient

from backend.core.aws import reset_clients
from backend.core.config import reset_settings
from scripts.local_setup import cliente_dynamo, crear_tablas, nombres_de_tabla, recurso_dynamo
from scripts.seed_data import TICKETS, cargar
from tests.helpers.fakes import (
    ExplodingLLM,
    FakeLLM,
    con_evidencia,
    fragmento,
    install_llm,
    install_rag,
    rag_prohibido,
    sin_evidencia,
)
from tests.helpers.http import DEV_SECRET


@pytest.fixture(scope="session", autouse=True)
def secretos_de_prueba():
    """Secretos de identidad (D-001) para toda la sesion de tests.

    En local suelen venir de `.env`; en CI no existe ese archivo y sin ellos cualquier request
    al chat responde 503. Se fijan con `setdefault` para respetar los que ya esten y se limpia
    la memoria de Settings, que pudo cargarse al importar `backend.api.main` en la coleccion.
    """
    os.environ.setdefault("VMC_IDENTITY_SECRET", "test-vmc-identity-secret")
    os.environ.setdefault("SESSION_SIGNING_KEY", "test-session-signing-key")
    # Las pruebas no deben depender del `~/.aws/config` de cada maquina: un perfil `[default]`
    # mal formado (p. ej. `services = http://localhost:4566`, donde va el NOMBRE de una seccion
    # `[services ...]`, no una URL) hace fallar la creacion de cualquier client boto3 nuevo, y
    # el error aparece en pruebas que no tienen nada que ver. Aqui los endpoints los fija
    # `.env`/el entorno, asi que el perfil no aporta nada.
    os.environ["AWS_CONFIG_FILE"] = os.devnull
    os.environ["AWS_SHARED_CREDENTIALS_FILE"] = os.devnull
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "local")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "local")
    # Los endpoints locales se fijan SIEMPRE, aunque `.env` los traiga vacios. Sin esto boto3
    # resuelve el endpoint real de AWS y la suite escribiria en la cuenta del que la corra: un
    # `.env` con las variables en blanco no puede convertirse en una escritura a produccion.
    # Mismos defaults que `scripts/local_setup.py` (docker-compose).
    if not os.environ.get("DYNAMODB_ENDPOINT_URL"):
        os.environ["DYNAMODB_ENDPOINT_URL"] = "http://localhost:8001"
    if not os.environ.get("SQS_ENDPOINT_URL"):
        os.environ["SQS_ENDPOINT_URL"] = "http://localhost:4566"
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
    """Borra restos de una corrida interrumpida: conversaciones `conv_test_*` y cualquier
    ticket que no sea del dataset base.

    Sin esto, una entidad de prueba abandonada aparece en los GSIs y rompe las aserciones de
    las consultas de lectura. Los tickets se filtran por id contra el seed (y no por prefijo)
    porque los que crea el backend llevan uuid: lo unico que se sabe de ellos es que no son
    del dataset.
    """
    dynamo = recurso_dynamo()
    nombres = nombres_de_tabla()
    conversaciones = dynamo.Table(nombres["conversations"])
    for item in conversaciones.scan().get("Items", []):
        if item["conversation_id"].startswith("conv_test_"):
            conversaciones.delete_item(Key={"conversation_id": item["conversation_id"]})
    tickets = dynamo.Table(nombres["tickets"])
    del_seed = {t["ticket_id"] for t in TICKETS}
    for item in tickets.scan().get("Items", []):
        if item["ticket_id"] not in del_seed:
            tickets.delete_item(Key={"ticket_id": item["ticket_id"]})


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


# ───────────────────────────── Limpieza de lo que crea cada prueba ─────────────────────────────


class Registro:
    """Lo que la prueba creo y hay que borrar al terminar. Llamarlo registra una conversacion
    (el caso de siempre: `limpiar(conversation_id)`); `.asesor`, `.ticket` y `.limite` para el
    resto. Una conversacion arrastra sus mensajes, sus filas de AIUsage y su ticket."""

    def __init__(self) -> None:
        self.conversaciones: list[str] = []
        self.asesores: list[str] = []
        self.tickets: list[str] = []
        self.limites: list[str] = []

    def __call__(self, conversation_id: str) -> None:
        self.conversaciones.append(conversation_id)

    conversacion = __call__

    def asesor(self, advisor_id: str) -> None:
        self.asesores.append(advisor_id)

    def ticket(self, ticket_id: str) -> None:
        self.tickets.append(ticket_id)

    def limite(self, limit_key: str) -> None:
        self.limites.append(limit_key)


def _borrar_por_conversacion(tablas, conversation_id: str) -> None:
    for tabla, sk in (("messages", "message_key"), ("ai_usage", "execution_key")):
        for item in tablas[tabla].query(
            KeyConditionExpression=Key("conversation_id").eq(conversation_id)
        )["Items"]:
            tablas[tabla].delete_item(Key={"conversation_id": conversation_id, sk: item[sk]})
    # Derivar abre un ticket (RF-023): sin borrarlo queda en el GSI de estado y rompe las
    # pruebas de lectura que cuentan los pendientes del dataset base.
    for item in tablas["tickets"].query(
        IndexName="gsi1_conversation",
        KeyConditionExpression=Key("conversation_id").eq(conversation_id),
    )["Items"]:
        tablas["tickets"].delete_item(Key={"ticket_id": item["ticket_id"]})
    tablas["conversations"].delete_item(Key={"conversation_id": conversation_id})


@pytest.fixture
def limpiar(tablas):
    """Registra lo creado por la prueba y lo borra al final (ver `Registro`). Las pruebas
    que escriben NUNCA tocan el dataset de `seed_data`: crean lo suyo y lo registran aqui."""
    registro = Registro()
    yield registro
    for conversation_id in registro.conversaciones:
        _borrar_por_conversacion(tablas, conversation_id)
    for ticket_id in registro.tickets:
        tablas["tickets"].delete_item(Key={"ticket_id": ticket_id})
    for advisor_id in registro.asesores:
        tablas["advisors"].delete_item(Key={"advisor_id": advisor_id})
    for limit_key in registro.limites:
        for item in tablas["rate_limits"].query(
            KeyConditionExpression=Key("limit_key").eq(limit_key)
        )["Items"]:
            tablas["rate_limits"].delete_item(
                Key={"limit_key": limit_key, "window": item["window"]}
            )


# ───────────────────────────── Configuracion por prueba ─────────────────────────────


@pytest.fixture
def sin_rate_limit(monkeypatch):
    """Apaga el tope por minuto (D-005) para las pruebas que mandan varios mensajes seguidos
    y no prueban ESE limite (que tiene tests/test_guardrails.py)."""
    monkeypatch.setenv("MAX_MESSAGES_PER_MINUTE", "0")
    reset_settings()
    yield
    reset_settings()


@pytest.fixture
def settings_limpios():
    """Por si una prueba corta a medias tras tocar variables de entorno de Settings."""
    yield
    reset_settings()


# ───────────────────────────── Dobles del modelo y del indice ─────────────────────────────


@pytest.fixture
def fake_llm(monkeypatch) -> FakeLLM:
    """Clasificador que dice FAQ y redactor con una respuesta fija; registra las llamadas."""
    return install_llm(monkeypatch, FakeLLM())


@pytest.fixture
def sin_llm(monkeypatch) -> ExplodingLLM:
    """El camino bajo prueba NO debe tocar un modelo: si lo hace, el test falla solo."""
    return install_llm(monkeypatch, ExplodingLLM())


@pytest.fixture
def sin_rag(monkeypatch):
    """Hubo un hit, pero bajo el umbral: no es evidencia (RF-018) y aun asi queda registrado
    para la consola de dev. Devuelve el fragmento descartado."""
    descartado = fragmento("poco relacionado", topic="Retiro de saldo", score=0.79, source_url=None)
    install_rag(monkeypatch, sin_evidencia(descartado))
    return descartado


@pytest.fixture
def con_rag(monkeypatch):
    """Un fragmento sobre el umbral: evidencia para el redactor. Devuelve el fragmento."""
    frag = fragmento()
    install_rag(monkeypatch, con_evidencia(frag))
    return frag


@pytest.fixture
def sin_rag_llamada(monkeypatch):
    """El camino bajo prueba NO debe tocar el indice (ofrecer botones, D-028)."""
    rag_prohibido(monkeypatch)


# ───────────────────────────── Clientes HTTP ─────────────────────────────


@pytest.fixture
def cola_falsa(monkeypatch):
    """Registra los jobs que la API intenta encolar, sin SQS."""
    enviados: list = []
    monkeypatch.setattr("backend.api.routers.chat.jobs.enqueue_ai_job", enviados.append)
    return enviados


@pytest.fixture
def client(cola_falsa):
    """El chat publico (`/chat/*`), con el encolado sustituido por `cola_falsa`."""
    from backend.api.main import app

    return TestClient(app)


@pytest.fixture
def advisor_client(monkeypatch, cola_falsa):
    """`/advisor/*` con el authorizer de dev (backend/api/dev_auth.py) en lugar de Cognito: el
    codigo de las rutas no distingue entornos, solo lee claims. Tambien sirve el chat publico
    (para crear la conversacion que el asesor atiende) y apaga el tope por minuto."""
    from backend.api import dev_auth
    from backend.api.main import app

    monkeypatch.setenv("ADVISOR_DEV_AUTH", "1")
    monkeypatch.setenv("ADVISOR_DEV_JWT_SECRET", DEV_SECRET)
    monkeypatch.setenv("MAX_MESSAGES_PER_MINUTE", "0")
    reset_settings()
    yield TestClient(dev_auth.DevCognitoAuthorizer(app))
    reset_settings()
