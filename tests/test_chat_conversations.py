"""Dominio conversaciones contra dynamodb-local — RF-004, RF-008, RF-038, D-002, D-003, AC-008.

Criterios:
  AC-C1  el usuario autenticado tiene UNA conversacion, siempre la misma (D-002 + D-003)
  AC-C2  el anonimo recibe una conversacion nueva por sesion y no queda indexado por usuario
         (RF-004: nada que recuperar entre sesiones)
  AC-C3  cada mensaje persiste conversation_id, remitente, timestamp, tipo y estado (RF-008)
         y actualiza los campos desnormalizados de la conversacion
  AC-C4  un reintento con el mismo client_message_id no duplica (RF-038 / RNF-004)
  AC-C5  los limites configurables se aplican (RF-014)
  AC-C6  los listados no exponen los marcadores de idempotencia y el cursor es exclusivo
"""

import uuid

import pytest
from boto3.dynamodb.conditions import Key

from backend.conversations import repository, service
from backend.conversations.models import Conversation, Message, UserType
from backend.core.auth import VmcIdentity
from backend.core.config import reset_settings

pytestmark = pytest.mark.usefixtures("entorno_dynamo")


@pytest.fixture
def limpiar(tablas):
    """Registra conversaciones creadas por la prueba y las borra (con sus mensajes) al final.

    Las de usuario autenticado tienen id determinista, asi que cada prueba usa un user_id
    unico para no pisarse con otra.
    """
    ids: list[str] = []
    yield ids.append
    for conversation_id in ids:
        items = tablas["messages"].query(
            KeyConditionExpression=Key("conversation_id").eq(conversation_id)
        )["Items"]
        for item in items:
            tablas["messages"].delete_item(
                Key={"conversation_id": conversation_id, "message_key": item["message_key"]}
            )
        tablas["conversations"].delete_item(Key={"conversation_id": conversation_id})


def _identidad(**extra) -> VmcIdentity:
    return VmcIdentity(user_id=f"user_test_{uuid.uuid4().hex[:8]}", **extra)


def _abrir(limpiar, identity=None):
    conversation, created = service.open_conversation(identity)
    limpiar(conversation.conversation_id)
    return conversation, created


# ───────────────────── AC-C1: una sola conversacion por usuario autenticado ─────────────────────


def test_el_autenticado_vuelve_siempre_a_la_misma_conversacion(limpiar, tablas):
    identity = _identidad(name="Carla", email="carla@example.test")

    primera, creada = _abrir(limpiar, identity)
    segunda, creada_otra_vez = _abrir(limpiar, identity)

    assert creada is True and creada_otra_vez is False
    assert primera.conversation_id == segunda.conversation_id
    assert segunda.user_type == UserType.AUTHENTICATED
    assert segunda.user_id == identity.user_id

    en_gsi = repository.find_conversations_by_user(identity.user_id)
    assert [c.conversation_id for c in en_gsi] == [primera.conversation_id], (
        "D-002: maximo 1 — el GSI por usuario no debe listar mas de una"
    )


def test_el_id_es_determinista_para_que_dos_pestañas_no_creen_dos(limpiar):
    identity = _identidad()
    esperado = service.conversation_id_for_user(identity.user_id)

    conversation, _ = _abrir(limpiar, identity)

    assert conversation.conversation_id == esperado
    # Carrera simulada: alguien ya creo el item; la creacion condicional lo detecta.
    assert repository.create_conversation(conversation) is False


def test_si_vmc_cambia_el_nombre_la_copia_local_se_actualiza(limpiar):
    identity = _identidad(name="Ana")
    _abrir(limpiar, identity)

    actualizada, _ = _abrir(limpiar, VmcIdentity(user_id=identity.user_id, name="Ana Maria"))

    assert actualizada.user_name == "Ana Maria"
    assert repository.get_conversation(actualizada.conversation_id).user_name == "Ana Maria"


# ─────────────────────── AC-C2: el anonimo no conserva ni recupera nada ───────────────────────


def test_cada_sesion_anonima_recibe_una_conversacion_distinta(limpiar):
    una, creada = _abrir(limpiar, None)
    otra, _ = _abrir(limpiar, None)

    assert creada is True
    assert una.conversation_id != otra.conversation_id
    assert una.user_type == UserType.ANONYMOUS


def test_la_conversacion_anonima_no_guarda_identidad(limpiar, tablas):
    conversation, _ = _abrir(limpiar, None)

    item = tablas["conversations"].get_item(
        Key={"conversation_id": conversation.conversation_id}
    )["Item"]

    for campo in ("user_id", "user_name", "user_email"):
        assert campo not in item, f"RF-002/RF-004: el anonimo no entrega {campo}"


# ───────────────────── AC-C3: lo que persiste cada mensaje (RF-008) ─────────────────────


def test_el_mensaje_persiste_los_campos_minimos_y_actualiza_la_conversacion(limpiar, tablas):
    conversation, _ = _abrir(limpiar, None)

    message, created = service.post_user_message(
        conversation, client_message_id="cli-" + uuid.uuid4().hex, content="  hola  "
    )

    assert created is True
    item = tablas["messages"].get_item(
        Key={"conversation_id": conversation.conversation_id, "message_key": message.message_key}
    )["Item"]
    assert item["sender_type"] == "USER"
    assert item["message_type"] == "TEXT"
    assert item["status"] == "RECEIVED", "estado tecnico: durable, pendiente del pipeline IA"
    assert item["content"] == "hola", "se guarda sin espacios sobrantes"
    assert item["message_key"] == f"{item['created_at']}#{item['message_id']}"

    actualizada = repository.get_conversation(conversation.conversation_id)
    assert actualizada.message_count == 1
    assert actualizada.last_message_preview == "hola"
    assert actualizada.last_message_at == message.created_at
    assert actualizada.unread_count == 0, "con el bot atendiendo no hay asesor que deba leerlo"


def test_con_el_bot_apagado_el_mensaje_cuenta_como_no_leido(limpiar, tablas):
    conversation, _ = _abrir(limpiar, None)
    tablas["conversations"].update_item(
        Key={"conversation_id": conversation.conversation_id},
        UpdateExpression="SET bot_enabled = :off",
        ExpressionAttributeValues={":off": False},
    )
    apagada = repository.get_conversation(conversation.conversation_id)

    service.post_user_message(apagada, client_message_id="cli-" + uuid.uuid4().hex, content="?")

    assert repository.get_conversation(conversation.conversation_id).unread_count == 1


def test_mensaje_a_conversacion_inexistente_falla_claro(limpiar):
    fantasma = Conversation(
        conversation_id=f"conv_test_{uuid.uuid4().hex[:8]}",
        user_type=UserType.ANONYMOUS,
        last_message_at="2026-08-27T00:00:00.000Z",
        created_at="2026-08-27T00:00:00.000Z",
        updated_at="2026-08-27T00:00:00.000Z",
    )
    limpiar(fantasma.conversation_id)

    with pytest.raises(repository.ConversationNotFound):
        service.post_user_message(fantasma, client_message_id="cli-12345678", content="hola")


# ───────────────────────── AC-C4: idempotencia del reintento (RF-038) ─────────────────────────


def test_reintento_con_el_mismo_client_message_id_devuelve_el_original(limpiar):
    conversation, _ = _abrir(limpiar, None)
    client_message_id = "cli-" + uuid.uuid4().hex

    original, creado = service.post_user_message(
        conversation, client_message_id=client_message_id, content="primer intento"
    )
    repetido, creado_de_nuevo = service.post_user_message(
        conversation, client_message_id=client_message_id, content="primer intento"
    )

    assert (creado, creado_de_nuevo) == (True, False)
    assert repetido.message_id == original.message_id
    assert repetido.message_key == original.message_key
    assert repository.get_conversation(conversation.conversation_id).message_count == 1
    assert len(repository.list_messages(conversation.conversation_id)) == 1


# ───────────────────────────── AC-C5: limites configurables ─────────────────────────────


def test_el_largo_maximo_del_mensaje_es_configurable(limpiar, monkeypatch):
    conversation, _ = _abrir(limpiar, None)
    monkeypatch.setenv("MAX_MESSAGE_CHARS", "10")
    reset_settings()
    try:
        with pytest.raises(service.MessageTooLong) as exc:
            service.post_user_message(
                conversation, client_message_id="cli-12345678", content="x" * 11
            )
        assert exc.value.limit == 10
    finally:
        reset_settings()


@pytest.mark.parametrize("content", ["", "   ", "\n\t"])
def test_el_mensaje_vacio_no_se_persiste(limpiar, content):
    conversation, _ = _abrir(limpiar, None)

    with pytest.raises(service.EmptyMessage):
        service.post_user_message(conversation, client_message_id="cli-12345678", content=content)


# ───────────────────── AC-C6: listados sin marcadores y cursor exclusivo ─────────────────────


def _enviar(conversation, texto) -> Message:
    message, _ = service.post_user_message(
        conversation, client_message_id="cli-" + uuid.uuid4().hex, content=texto
    )
    return message


def test_el_listado_es_cronologico_y_sin_marcadores(limpiar, tablas):
    conversation, _ = _abrir(limpiar, None)
    enviados = [_enviar(conversation, f"mensaje {i}") for i in range(3)]

    listado = repository.list_messages(conversation.conversation_id)

    assert [m.content for m in listado] == ["mensaje 0", "mensaje 1", "mensaje 2"]
    crudos = tablas["messages"].query(
        KeyConditionExpression=Key("conversation_id").eq(conversation.conversation_id)
    )["Items"]
    assert len(crudos) == 6, "3 mensajes + 3 marcadores CMID# en la tabla"
    assert all(not repository.is_idempotency_marker(m.model_dump()) for m in listado)
    assert listado[-1].message_key == enviados[-1].message_key


def test_el_cursor_after_entrega_solo_lo_nuevo(limpiar):
    conversation, _ = _abrir(limpiar, None)
    primero = _enviar(conversation, "viejo")
    segundo = _enviar(conversation, "nuevo")

    nuevos = repository.list_messages(conversation.conversation_id, after=primero.message_key)

    assert [m.message_key for m in nuevos] == [segundo.message_key]
    assert repository.list_messages(conversation.conversation_id, after=segundo.message_key) == []


def test_la_ventana_reciente_devuelve_los_ultimos_n_en_orden(limpiar):
    """RF-013: la IA recibe los N mas recientes, no los N primeros ni marcadores."""
    conversation, _ = _abrir(limpiar, None)
    for i in range(4):
        _enviar(conversation, f"m{i}")

    ventana = repository.list_recent_messages(conversation.conversation_id, limit=2)

    assert [m.content for m in ventana] == ["m2", "m3"]
