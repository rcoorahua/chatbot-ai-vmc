"""API publica del widget (`/chat/*`) — RF-001, RF-004, RF-005, RF-008, AC-008, T8.

Criterios:
  AC-P1  el chat abre sin login: una sesion anonima da token y conversacion (RF-001/RF-002)
  AC-P2  con el JWT de VMC la sesion queda asociada a la identidad y saluda por nombre (AC-008)
  AC-P3  identidad invalida = 401 (no se degrada a anonimo en silencio); sin secreto = 503
  AC-P4  una sesion solo ve su conversacion (403 para cualquier otra)
  AC-P5  enviar responde 202, persiste y encola UN job por mensaje nuevo (T8); el reintento no
         re-encola; si la cola falla el mensaje queda marcado, no perdido (RNF-003)
  AC-P6  el sondeo con `after` entrega solo lo nuevo

El encolado a SQS se sustituye por un doble en estas pruebas; el contrato real con localstack
se verifica aparte al final.
"""

import os
import uuid

import boto3
import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.api.routers import chat as chat_router
from backend.core import auth, jobs
from backend.core.clock import epoch_seconds
from backend.core.config import get_settings, reset_settings

pytestmark = pytest.mark.usefixtures("entorno_dynamo")


@pytest.fixture
def cola_falsa(monkeypatch):
    """Registra los jobs que la API intenta encolar, sin SQS."""
    enviados: list[jobs.AIJob] = []
    monkeypatch.setattr(chat_router.jobs, "enqueue_ai_job", enviados.append)
    return enviados


@pytest.fixture
def client(cola_falsa):
    return TestClient(app)


@pytest.fixture
def limpiar(tablas):
    from boto3.dynamodb.conditions import Key

    ids: list[str] = []
    yield ids.append
    for conversation_id in ids:
        for item in tablas["messages"].query(
            KeyConditionExpression=Key("conversation_id").eq(conversation_id)
        )["Items"]:
            tablas["messages"].delete_item(
                Key={"conversation_id": conversation_id, "message_key": item["message_key"]}
            )
        tablas["conversations"].delete_item(Key={"conversation_id": conversation_id})


def _jwt_vmc(user_id: str, **claims) -> str:
    payload = {"sub": user_id, "exp": epoch_seconds() + 600, **claims}
    return auth.sign_jwt(payload, get_settings().vmc_identity_secret)


def _sesion(client, limpiar, user_jwt: str | None = None) -> dict:
    body = {"user_jwt": user_jwt} if user_jwt else {}
    response = client.post("/chat/sessions", json=body)
    assert response.status_code == 201, response.text
    data = response.json()
    limpiar(data["conversation"]["conversation_id"])
    return data


def _auth(sesion: dict) -> dict:
    return {"Authorization": f"Bearer {sesion['token']}"}


def _enviar(client, sesion, texto="hola", client_message_id=None) -> dict:
    response = client.post(
        f"/chat/conversations/{sesion['conversation']['conversation_id']}/messages",
        json={
            "client_message_id": client_message_id or "cli-" + uuid.uuid4().hex,
            "content": texto,
        },
        headers=_auth(sesion),
    )
    assert response.status_code == 202, response.text
    return response.json()


# ───────────────────────────── AC-P1: anonimo sin login ─────────────────────────────


def test_sesion_anonima_abre_sin_datos(client, limpiar):
    sesion = _sesion(client, limpiar)

    assert sesion["user"] == {"type": "ANONYMOUS", "name": None}
    assert sesion["conversation"]["user_type"] == "ANONYMOUS"
    assert sesion["conversation"]["status"] == "BOT_ATTENDING"
    assert sesion["created"] is True
    assert sesion["token"]


def test_la_sesion_informa_el_limite_de_caracteres(client, limpiar, monkeypatch):
    """El widget corta en el limite REAL del servidor (D-005), no en uno copiado.

    Si el numero viviera en `widget/subastin.js`, subir `MAX_MESSAGE_CHARS` en `.env` dejaria
    al widget cortando en el valor viejo sin que nada avisara: el usuario no podria escribir lo
    que el servidor si acepta. Por eso viaja en la sesion.
    """
    sesion = _sesion(client, limpiar)
    assert sesion["limits"]["max_message_chars"] == get_settings().max_message_chars

    monkeypatch.setenv("MAX_MESSAGE_CHARS", "500")
    reset_settings()
    try:
        assert _sesion(client, limpiar)["limits"]["max_message_chars"] == 500
    finally:
        monkeypatch.delenv("MAX_MESSAGE_CHARS", raising=False)
        reset_settings()


def test_la_sesion_trae_el_enlace_para_crear_cuenta(client, limpiar, monkeypatch):
    """D-031: la URL a la que el widget manda al visitante la decide el servidor
    (`VMC_SIGNUP_URL`, mock hasta que VMC confirme la real), no una constante del widget."""
    monkeypatch.setenv("VMC_SIGNUP_URL", "https://vmc.example.test/crear-cuenta")
    reset_settings()
    try:
        assert _sesion(client, limpiar)["links"]["signup"] == "https://vmc.example.test/crear-cuenta"
    finally:
        monkeypatch.delenv("VMC_SIGNUP_URL", raising=False)
        reset_settings()


def test_dos_sesiones_anonimas_no_comparten_conversacion(client, limpiar):
    una = _sesion(client, limpiar)
    otra = _sesion(client, limpiar)

    assert una["conversation"]["conversation_id"] != otra["conversation"]["conversation_id"]


# ───────────────────────────── AC-P2: autenticado por VMC ─────────────────────────────


def test_sesion_autenticada_queda_asociada_a_la_identidad_vmc(client, limpiar):
    user_id = "vmc_" + uuid.uuid4().hex[:8]

    primera = _sesion(client, limpiar, _jwt_vmc(user_id, name="Aaron", email="a@example.test"))
    segunda = _sesion(client, limpiar, _jwt_vmc(user_id, name="Aaron", email="a@example.test"))

    assert primera["user"] == {"type": "AUTHENTICATED", "name": "Aaron"}, "saludo por nombre"
    assert primera["created"] is True and segunda["created"] is False
    assert (
        primera["conversation"]["conversation_id"] == segunda["conversation"]["conversation_id"]
    ), "D-002/D-003: la misma conversacion en cada visita"
    assert auth.decode_session_token(segunda["token"]).user_id == user_id


# ───────────────────────────── AC-P3: identidad invalida ─────────────────────────────


@pytest.mark.parametrize(
    "user_jwt",
    [
        "no-es-un-jwt",
        auth.sign_jwt({"sub": "1", "exp": epoch_seconds() + 600}, "secreto-equivocado"),
        auth.sign_jwt({"sub": "1", "exp": epoch_seconds() - 5}, "test-vmc-identity-secret"),
    ],
)
def test_identidad_invalida_es_401_y_no_anonimo(client, user_jwt):
    response = client.post("/chat/sessions", json={"user_jwt": user_jwt})

    assert response.status_code == 401


def test_sin_secreto_de_vmc_configurado_responde_503(client, monkeypatch):
    monkeypatch.setenv("VMC_IDENTITY_SECRET", "")
    reset_settings()
    try:
        response = client.post("/chat/sessions", json={"user_jwt": "a.b.c"})
    finally:
        reset_settings()

    assert response.status_code == 503


def test_sin_session_signing_key_responde_503_y_no_crea_conversacion(client, monkeypatch, tablas):
    # DETAILS.md §4.2: el chequeo debe correr ANTES de abrir la conversacion (tambien la del
    # anonimo, que no manda user_jwt) — si no, cada intento sin la clave deja una fila huerfana.
    antes = tablas["conversations"].scan()["Count"]
    monkeypatch.setenv("SESSION_SIGNING_KEY", "")
    reset_settings()
    try:
        response = client.post("/chat/sessions", json={})
    finally:
        reset_settings()

    assert response.status_code == 503
    assert tablas["conversations"].scan()["Count"] == antes


# ───────────────────────────── AC-P4: cada sesion, su conversacion ─────────────────────────────


def test_sin_token_no_hay_acceso(client, limpiar):
    sesion = _sesion(client, limpiar)
    conversation_id = sesion["conversation"]["conversation_id"]

    assert client.get(f"/chat/conversations/{conversation_id}").status_code == 401


def test_una_sesion_no_ve_la_conversacion_de_otra(client, limpiar):
    mia = _sesion(client, limpiar)
    ajena = _sesion(client, limpiar)
    ajena_id = ajena["conversation"]["conversation_id"]

    assert client.get(f"/chat/conversations/{ajena_id}", headers=_auth(mia)).status_code == 403
    assert (
        client.get(f"/chat/conversations/{ajena_id}/messages", headers=_auth(mia)).status_code
        == 403
    )
    assert (
        client.post(
            f"/chat/conversations/{ajena_id}/messages",
            json={"client_message_id": "cli-12345678", "content": "hola"},
            headers=_auth(mia),
        ).status_code
        == 403
    )


def test_la_sesion_ve_su_propia_conversacion(client, limpiar):
    sesion = _sesion(client, limpiar)
    conversation_id = sesion["conversation"]["conversation_id"]

    response = client.get(f"/chat/conversations/{conversation_id}", headers=_auth(sesion))

    assert response.status_code == 200
    assert response.json()["conversation_id"] == conversation_id


# ───────────────────── AC-P5: enviar = 202 + persistir + encolar ─────────────────────


def test_enviar_persiste_y_encola_un_job(client, limpiar, cola_falsa):
    sesion = _sesion(client, limpiar)

    aceptado = _enviar(client, sesion, "como participo en una subasta?")

    assert aceptado["duplicate"] is False
    mensaje = aceptado["message"]
    assert mensaje["sender_type"] == "USER"
    assert mensaje["status"] == "RECEIVED"
    assert mensaje["content"] == "como participo en una subasta?"
    assert len(cola_falsa) == 1
    assert cola_falsa[0].conversation_id == sesion["conversation"]["conversation_id"]
    assert cola_falsa[0].message_id == mensaje["message_id"]


def test_el_reintento_no_duplica_ni_reencola(client, limpiar, cola_falsa):
    sesion = _sesion(client, limpiar)
    client_message_id = "cli-" + uuid.uuid4().hex

    primero = _enviar(client, sesion, "hola", client_message_id)
    segundo = _enviar(client, sesion, "hola", client_message_id)

    assert segundo["duplicate"] is True
    assert segundo["message"]["message_id"] == primero["message"]["message_id"]
    assert len(cola_falsa) == 1, "el job del original ya esta en camino"


def test_si_la_cola_falla_el_mensaje_queda_marcado_no_perdido(client, limpiar, monkeypatch):
    def cola_caida(job):
        raise RuntimeError("SQS no responde")

    monkeypatch.setattr(chat_router.jobs, "enqueue_ai_job", cola_caida)
    sesion = _sesion(client, limpiar)

    aceptado = _enviar(client, sesion, "hola")

    assert aceptado["message"]["status"] == "QUEUE_FAILED"
    conversation_id = sesion["conversation"]["conversation_id"]
    listado = client.get(f"/chat/conversations/{conversation_id}/messages", headers=_auth(sesion))
    assert [m["status"] for m in listado.json()["messages"]] == ["QUEUE_FAILED"]


def test_el_mensaje_demasiado_largo_es_422(client, limpiar, monkeypatch):
    sesion = _sesion(client, limpiar)
    monkeypatch.setenv("MAX_MESSAGE_CHARS", "5")
    reset_settings()
    try:
        response = client.post(
            f"/chat/conversations/{sesion['conversation']['conversation_id']}/messages",
            json={"client_message_id": "cli-12345678", "content": "demasiado largo"},
            headers=_auth(sesion),
        )
    finally:
        reset_settings()

    assert response.status_code == 422


@pytest.mark.parametrize("client_message_id", ["corto", "con espacios 123", "x" * 65])
def test_client_message_id_invalido_es_422(client, limpiar, client_message_id):
    sesion = _sesion(client, limpiar)

    response = client.post(
        f"/chat/conversations/{sesion['conversation']['conversation_id']}/messages",
        json={"client_message_id": client_message_id, "content": "hola"},
        headers=_auth(sesion),
    )

    assert response.status_code == 422


# ───────────────────────────── AC-P6: sondeo incremental ─────────────────────────────


def test_el_sondeo_con_after_entrega_solo_lo_nuevo(client, limpiar):
    sesion = _sesion(client, limpiar)
    conversation_id = sesion["conversation"]["conversation_id"]
    _enviar(client, sesion, "primero")

    todo = client.get(f"/chat/conversations/{conversation_id}/messages", headers=_auth(sesion))
    assert [m["content"] for m in todo.json()["messages"]] == ["primero"]
    cursor = todo.json()["next_after"]

    _enviar(client, sesion, "segundo")
    nuevos = client.get(
        f"/chat/conversations/{conversation_id}/messages",
        params={"after": cursor},
        headers=_auth(sesion),
    )
    assert [m["content"] for m in nuevos.json()["messages"]] == ["segundo"]

    nada = client.get(
        f"/chat/conversations/{conversation_id}/messages",
        params={"after": nuevos.json()["next_after"]},
        headers=_auth(sesion),
    )
    assert nada.json()["messages"] == []
    assert nada.json()["next_after"] == nuevos.json()["next_after"], "el cursor no retrocede"


# ───────────────────────────── Contrato real con SQS (localstack) ─────────────────────────────


def test_el_job_llega_a_la_cola_y_el_worker_puede_leerlo(monkeypatch):
    """T8/T3: lo que la API encola es exactamente lo que `AIJob` valida en el worker."""
    endpoint = os.environ.get("SQS_ENDPOINT_URL", "http://localhost:4566")
    sqs = boto3.client(
        "sqs",
        endpoint_url=endpoint,
        region_name="us-east-1",
        aws_access_key_id="local",
        aws_secret_access_key="local",
    )
    try:
        queue_url = sqs.create_queue(QueueName="subastin-test-ai-jobs")["QueueUrl"]
    except Exception:  # noqa: BLE001 — localstack apagado
        if os.environ.get("CI"):
            pytest.fail("localstack no responde en CI. Revisar el bloque `services` de ci.yml.")
        pytest.skip("localstack no esta arriba — levantarlo con: docker compose up -d")

    monkeypatch.setenv("AI_JOBS_QUEUE_URL", queue_url)
    monkeypatch.setenv("SQS_ENDPOINT_URL", endpoint)
    # Sin debounce: aqui se valida el payload que viaja por SQS, no la espera de D-020 (el
    # DelaySeconds tiene su propio test en test_ai_worker). Con el retraso real, el receive de
    # abajo no veria el mensaje dentro de sus 2 segundos.
    monkeypatch.setenv("AI_DEBOUNCE_SECONDS", "0")
    reset_settings()
    from backend.core.aws import reset_clients

    reset_clients()
    try:
        job = jobs.AIJob(
            conversation_id="conv_test_sqs",
            message_id="msg_1",
            message_key="2026-08-27T00:00:00.000Z#msg_1",
            requested_at="2026-08-27T00:00:00.000Z",
        )
        jobs.enqueue_ai_job(job)

        recibido = sqs.receive_message(QueueUrl=queue_url, WaitTimeSeconds=2)["Messages"][0]
        assert jobs.AIJob.model_validate_json(recibido["Body"]) == job
        sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=recibido["ReceiptHandle"])
    finally:
        reset_settings()
        reset_clients()
