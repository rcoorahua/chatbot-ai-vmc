"""Limites contra abuso (RF-014 / D-005) y ventana de contexto de la IA (RF-013 / D-004).

Criterios:
  AC-G1  el rate limit frena la rafaga: pasado el maximo por minuto la API responde 429 con
         `Retry-After`, y el mensaje rechazado NO se persiste
  AC-G2  la cuota es del usuario: las respuestas del bot/asesor no la consumen, y una
         conversacion no gasta la de otra
  AC-G3  el limite es configuracion (RNF-007): cambiar la variable cambia el comportamiento,
         y 0 lo desactiva
  AC-G4  la ventana de contexto son los ultimos N mensajes DE LA ULTIMA HORA: lo anterior a la
         ventana no entra, aunque haya menos de N mensajes
  AC-G5  no hay resumen (D-004): `summary` sigue vacio por mucho que crezca la conversacion

Los timestamps viejos se escriben directo en la tabla: la SK ES el timestamp, asi que un item
con `created_at` de hace dos horas es indistinguible de uno que se escribio hace dos horas.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.api.routers import chat as chat_router
from backend.conversations import repository, service
from backend.conversations.models import (
    Conversation,
    Message,
    MessageStatus,
    MessageType,
    SenderType,
    UserType,
    message_key_for,
)
from backend.core.clock import minutes_ago_iso, utc_now_iso
from backend.core.config import get_settings, reset_settings

pytestmark = pytest.mark.usefixtures("entorno_dynamo")


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


@pytest.fixture
def conversacion(limpiar) -> Conversation:
    now = utc_now_iso()
    conversation = Conversation(
        conversation_id="conv_test_" + uuid.uuid4().hex[:8],
        user_type=UserType.ANONYMOUS,
        last_message_at=now,
        created_at=now,
        updated_at=now,
    )
    repository.create_conversation(conversation)
    limpiar(conversation.conversation_id)
    return conversation


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(chat_router.jobs, "enqueue_ai_job", lambda job: None)
    return TestClient(app)


@pytest.fixture(autouse=True)
def _settings_limpios():
    yield
    reset_settings()


def _escribir(conversation_id: str, texto: str, *, created_at: str, sender=SenderType.USER):
    """Escribe un mensaje con un timestamp arbitrario (para simular el paso del tiempo)."""
    message_id = str(uuid.uuid4())
    repository.put_message(
        Message(
            conversation_id=conversation_id,
            message_key=message_key_for(created_at, message_id),
            message_id=message_id,
            sender_type=sender,
            message_type=MessageType.TEXT,
            status=MessageStatus.DELIVERED,
            content=texto,
            created_at=created_at,
        )
    )


def _enviar(conversation, texto="hola"):
    return service.post_user_message(
        conversation, client_message_id="cli-" + uuid.uuid4().hex, content=texto
    )


# ───────────────────────────── AC-G1: la rafaga se frena ─────────────────────────────


def test_pasado_el_maximo_por_minuto_el_mensaje_se_rechaza(conversacion, monkeypatch):
    monkeypatch.setenv("MAX_MESSAGES_PER_MINUTE", "3")
    reset_settings()

    for i in range(3):
        _enviar(conversacion, f"mensaje {i}")

    with pytest.raises(service.RateLimited) as error:
        _enviar(conversacion, "uno de mas")
    assert error.value.limit == 3
    assert error.value.retry_after == 60


def test_el_mensaje_rechazado_no_se_persiste(conversacion, monkeypatch):
    monkeypatch.setenv("MAX_MESSAGES_PER_MINUTE", "2")
    reset_settings()
    _enviar(conversacion, "uno")
    _enviar(conversacion, "dos")

    with pytest.raises(service.RateLimited):
        _enviar(conversacion, "tres")

    contenidos = [m.content for m in repository.list_messages(conversacion.conversation_id)]
    assert contenidos == ["uno", "dos"], "el rechazado no entra al hilo"


def test_la_api_responde_429_con_retry_after(client, limpiar, monkeypatch):
    monkeypatch.setenv("MAX_MESSAGES_PER_MINUTE", "2")
    reset_settings()
    sesion = client.post("/chat/sessions", json={}).json()
    limpiar(sesion["conversation"]["conversation_id"])
    url = f"/chat/conversations/{sesion['conversation']['conversation_id']}/messages"
    headers = {"Authorization": f"Bearer {sesion['token']}"}

    for i in range(2):
        enviado = client.post(
            url, json={"client_message_id": f"cli-rate-{i:04d}", "content": "hola"}, headers=headers
        )
        assert enviado.status_code == 202

    frenado = client.post(
        url, json={"client_message_id": "cli-rate-9999", "content": "hola"}, headers=headers
    )
    assert frenado.status_code == 429
    assert frenado.headers["Retry-After"] == "60"
    assert "rapido" in frenado.json()["detail"]


def test_los_mensajes_viejos_no_cuentan_para_la_cuota(conversacion, monkeypatch):
    monkeypatch.setenv("MAX_MESSAGES_PER_MINUTE", "2")
    reset_settings()
    for i in range(5):
        _escribir(conversacion.conversation_id, f"viejo {i}", created_at=minutes_ago_iso(5))

    _enviar(conversacion, "nuevo")  # la ventana de un minuto esta vacia: pasa


# ───────────────────────────── AC-G2: la cuota es del usuario ─────────────────────────────


def test_las_respuestas_del_bot_y_del_asesor_no_gastan_la_cuota(conversacion, monkeypatch):
    monkeypatch.setenv("MAX_MESSAGES_PER_MINUTE", "2")
    reset_settings()
    now = utc_now_iso()
    for sender in (SenderType.BOT, SenderType.ADVISOR, SenderType.SYSTEM):
        _escribir(conversacion.conversation_id, f"de {sender}", created_at=now, sender=sender)

    _enviar(conversacion, "uno")
    _enviar(conversacion, "dos")  # solo cuentan los dos mios


def test_la_cuota_de_una_conversacion_no_afecta_a_otra(conversacion, limpiar, monkeypatch):
    monkeypatch.setenv("MAX_MESSAGES_PER_MINUTE", "1")
    reset_settings()
    _enviar(conversacion, "uno")

    otra, _ = service.open_conversation(None)
    limpiar(otra.conversation_id)
    _enviar(otra, "uno")  # cuota propia


# ───────────────────────────── AC-G3: es configuracion ─────────────────────────────


def test_el_limite_se_cambia_por_variable_de_entorno(conversacion, monkeypatch):
    monkeypatch.setenv("MAX_MESSAGES_PER_MINUTE", "1")
    reset_settings()
    _enviar(conversacion, "uno")
    with pytest.raises(service.RateLimited):
        _enviar(conversacion, "dos")

    monkeypatch.setenv("MAX_MESSAGES_PER_MINUTE", "5")
    reset_settings()
    _enviar(conversacion, "dos")  # el mismo caso ahora pasa


def test_cero_desactiva_el_limite(conversacion, monkeypatch):
    monkeypatch.setenv("MAX_MESSAGES_PER_MINUTE", "0")
    reset_settings()
    for i in range(12):
        _enviar(conversacion, f"mensaje {i}")


def test_los_valores_por_defecto_son_los_de_la_decision():
    """D-005/D-004 cerradas 28/08/2026: si alguien cambia un default, este test lo canta."""
    settings = get_settings()
    assert settings.max_messages_per_minute == 10
    assert settings.max_message_chars == 500
    assert settings.ai_context_messages == 20
    assert settings.ai_context_window_minutes == 60
    assert settings.max_image_bytes == 5 * 1024 * 1024
    assert settings.max_images_per_message == 3
    assert settings.max_images_per_hour == 20
    assert settings.image_types == ["image/jpeg", "image/png", "image/webp"]


# ───────────────────────────── AC-G4: ventana de contexto ─────────────────────────────


def test_la_ventana_deja_fuera_lo_anterior_a_una_hora(conversacion):
    _escribir(conversacion.conversation_id, "de ayer", created_at=minutes_ago_iso(1500))
    _escribir(conversacion.conversation_id, "hace dos horas", created_at=minutes_ago_iso(120))
    _escribir(conversacion.conversation_id, "hace media hora", created_at=minutes_ago_iso(30))
    _escribir(conversacion.conversation_id, "ahora", created_at=utc_now_iso())

    ventana = service.context_window(conversacion.conversation_id)

    assert [m.content for m in ventana] == ["hace media hora", "ahora"]


def test_si_vuelve_despues_de_la_ventana_solo_va_su_mensaje_nuevo(conversacion):
    for i in range(5):
        _escribir(conversacion.conversation_id, f"viejo {i}", created_at=minutes_ago_iso(180))
    _enviar(conversacion, "y esto como lo hago?")

    ventana = service.context_window(conversacion.conversation_id)

    assert [m.content for m in ventana] == ["y esto como lo hago?"]


def test_la_ventana_se_corta_en_los_ultimos_n_aunque_todos_sean_recientes(
    conversacion, monkeypatch
):
    monkeypatch.setenv("AI_CONTEXT_MESSAGES", "5")
    monkeypatch.setenv("MAX_MESSAGES_PER_MINUTE", "0")
    reset_settings()
    for i in range(8):
        _enviar(conversacion, f"m{i}")

    ventana = service.context_window(conversacion.conversation_id)

    assert [m.content for m in ventana] == ["m3", "m4", "m5", "m6", "m7"]


def test_la_ventana_sale_en_orden_cronologico_y_sin_marcadores(conversacion, monkeypatch):
    monkeypatch.setenv("MAX_MESSAGES_PER_MINUTE", "0")
    reset_settings()
    for i in range(3):
        _enviar(conversacion, f"m{i}")

    ventana = service.context_window(conversacion.conversation_id)

    assert [m.content for m in ventana] == ["m0", "m1", "m2"]
    assert all(not repository.is_idempotency_marker(m.model_dump()) for m in ventana)


def test_la_ventana_de_una_conversacion_sin_mensajes_recientes_esta_vacia(conversacion):
    _escribir(conversacion.conversation_id, "viejo", created_at=minutes_ago_iso(90))

    assert service.context_window(conversacion.conversation_id) == []


# ───────────────────────────── AC-G5: sin resumen ─────────────────────────────


def test_no_se_genera_resumen_por_mucho_que_crezca_la_conversacion(conversacion, monkeypatch):
    monkeypatch.setenv("MAX_MESSAGES_PER_MINUTE", "0")
    reset_settings()
    for i in range(30):
        _enviar(conversacion, f"mensaje {i}")

    actual = repository.get_conversation(conversacion.conversation_id)
    assert actual.summary is None, "D-004: no hay resumen acumulado"
    assert actual.summary_updated_at is None
