"""API del asesor (`/advisor/*`) — RF-012, RF-029, RF-031..036, RF-038, AC-005, AC-006.

Criterios:
  AC-A1  sin token de Cognito (o con el token de sesion del widget) la ruta es 401, igual que
         responde el authorizer del API Gateway (T1)
  AC-A2  el asesor se resuelve por `sub`: auto-alta ACTIVE al primer login (RF-006), INVITED
         pasa a ACTIVE, DISABLED es 403, y `last_login_at` se registra
  AC-A3  la bandeja lista por estado y "mis casos" (RF-032), pendientes primero
  AC-A4  la toma es atomica: de dos asesores solo uno gana y el otro recibe 409 con el estado
         actual (RF-029 / AC-005); tomar apaga el bot y deja la nota ADVISOR_ASSIGNED
  AC-A5  responder exige haber tomado la conversacion (409 si no); la respuesta nace DELIVERED,
         firmada por el asesor, y el reintento con el mismo client_message_id no duplica (AC-006)
  AC-A6  el hilo entrega los ultimos N con paginacion hacia atras (RF-012/033), `after` trae
         solo lo nuevo, y abrirlo consume los no leidos (RF-035)
  AC-A7  cerrar el caso exige ser el asignado; deja la nota TICKET_CLOSED y devuelve la
         conversacion a BOT_ATTENDING con el bot encendido (RF-031 + D-003)

El authorizer se simula con el mismo middleware que usa el dev local (backend/api/dev_auth.py):
el codigo de las rutas no distingue entornos, solo lee claims del evento.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from backend.api import dev_auth
from backend.api.main import app
from backend.api.routers import chat as chat_router
from backend.core import auth
from backend.core.clock import epoch_seconds
from backend.core.config import get_settings, reset_settings

pytestmark = pytest.mark.usefixtures("entorno_dynamo")

DEV_SECRET = "test-advisor-dev-secret"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ADVISOR_DEV_AUTH", "1")
    monkeypatch.setenv("ADVISOR_DEV_JWT_SECRET", DEV_SECRET)
    reset_settings()
    monkeypatch.setattr(chat_router.jobs, "enqueue_ai_job", lambda job: None)
    yield TestClient(dev_auth.DevCognitoAuthorizer(app))
    reset_settings()


@pytest.fixture
def limpiar(tablas):
    from boto3.dynamodb.conditions import Key

    conversaciones: list[str] = []
    asesores: list[str] = []

    class Registro:
        conversacion = staticmethod(conversaciones.append)
        asesor = staticmethod(asesores.append)

    yield Registro
    for conversation_id in conversaciones:
        for item in tablas["messages"].query(
            KeyConditionExpression=Key("conversation_id").eq(conversation_id)
        )["Items"]:
            tablas["messages"].delete_item(
                Key={"conversation_id": conversation_id, "message_key": item["message_key"]}
            )
        tablas["conversations"].delete_item(Key={"conversation_id": conversation_id})
    for advisor_id in asesores:
        tablas["advisors"].delete_item(Key={"advisor_id": advisor_id})


def _token(sub: str, *, name: str | None = None, email: str | None = None, **extra) -> str:
    payload = {"sub": sub, "token_use": "id", "exp": epoch_seconds() + 600, **extra}
    if name:
        payload["name"] = name
    if email:
        payload["email"] = email
    return auth.sign_jwt(payload, DEV_SECRET)


def _bearer(sub: str, **claims) -> dict:
    return {"Authorization": f"Bearer {_token(sub, **claims)}"}


def _asesor_nuevo(client, limpiar, *, name="Ana Prueba") -> tuple[str, dict]:
    """Un asesor efimero (sub aleatorio) para no contaminar los GSI de otras pruebas."""
    sub = "sub-test-" + uuid.uuid4().hex[:8]
    headers = _bearer(sub, name=name, email=f"{sub}@vmc.test")
    me = client.get("/advisor/me", headers=headers)
    assert me.status_code == 200, me.text
    limpiar.asesor(me.json()["advisor_id"])
    return me.json()["advisor_id"], headers


def _conversacion_de_usuario(client, limpiar, *, autenticado=True) -> dict:
    """Sesion del widget: la conversacion que el asesor va a atender."""
    body = {}
    if autenticado:
        user_id = "vmc_" + uuid.uuid4().hex[:8]
        body["user_jwt"] = auth.sign_jwt(
            {"sub": user_id, "exp": epoch_seconds() + 600, "name": "Jorge", "email": "j@x.test"},
            get_settings().vmc_identity_secret,
        )
    response = client.post("/chat/sessions", json=body)
    assert response.status_code == 201, response.text
    sesion = response.json()
    limpiar.conversacion(sesion["conversation"]["conversation_id"])
    return sesion


def _usuario_escribe(client, sesion, texto="hola") -> dict:
    response = client.post(
        f"/chat/conversations/{sesion['conversation']['conversation_id']}/messages",
        json={"client_message_id": "cli-" + uuid.uuid4().hex, "content": texto},
        headers={"Authorization": f"Bearer {sesion['token']}"},
    )
    assert response.status_code == 202, response.text
    return response.json()["message"]


def _tomar(client, headers, conversation_id) -> dict:
    response = client.post(f"/advisor/conversations/{conversation_id}/take", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


# ───────────────────────────── AC-A1: 401 como el authorizer ─────────────────────────────


def test_sin_token_es_401_con_el_cuerpo_del_api_gateway(client):
    response = client.get("/advisor/me")
    assert response.status_code == 401
    assert response.json() == {"message": "Unauthorized"}


def test_el_token_de_sesion_del_widget_no_sirve_como_asesor(client, limpiar):
    sesion = _conversacion_de_usuario(client, limpiar, autenticado=False)
    response = client.get("/advisor/me", headers={"Authorization": f"Bearer {sesion['token']}"})
    assert response.status_code == 401


def test_un_access_token_no_es_un_id_token(client):
    payload = {"sub": "x", "token_use": "access", "exp": epoch_seconds() + 60}
    token = auth.sign_jwt(payload, DEV_SECRET)
    response = client.get("/advisor/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_el_chat_publico_no_pasa_por_el_authorizer(client):
    assert client.post("/chat/sessions", json={}).status_code == 201


# ───────────────────────────── AC-A2: resolver al asesor ─────────────────────────────


def test_auto_alta_al_primer_login_y_misma_fila_despues(client, limpiar):
    advisor_id, headers = _asesor_nuevo(client, limpiar, name="Nueva Asesora")

    otra_vez = client.get("/advisor/me", headers=headers).json()
    assert otra_vez["advisor_id"] == advisor_id
    assert otra_vez["status"] == "ACTIVE" and otra_vez["role"] == "ADVISOR"
    assert otra_vez["name"] == "Nueva Asesora"
    assert otra_vez["last_login_at"]


def test_el_asesor_del_seed_se_resuelve_por_sub_y_el_invitado_se_activa(client, tablas):
    ana = client.get("/advisor/me", headers=_bearer("sub-ana-001", name="Ana Torres")).json()
    assert ana["advisor_id"] == "adv_001"

    luis = client.get("/advisor/me", headers=_bearer("sub-luis-002", name="Luis Ramos")).json()
    assert luis["advisor_id"] == "adv_002" and luis["status"] == "ACTIVE"
    # Se devuelve el seed a su estado para las demas pruebas.
    tablas["advisors"].update_item(
        Key={"advisor_id": "adv_002"},
        UpdateExpression="SET #s = :invited REMOVE last_login_at",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":invited": "INVITED"},
    )


def test_el_asesor_deshabilitado_es_403(client, limpiar, tablas):
    advisor_id, headers = _asesor_nuevo(client, limpiar)
    tablas["advisors"].update_item(
        Key={"advisor_id": advisor_id},
        UpdateExpression="SET #s = :disabled",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":disabled": "DISABLED"},
    )
    assert client.get("/advisor/me", headers=headers).status_code == 403


# ───────────────────────────── AC-A3: bandeja ─────────────────────────────


def test_la_bandeja_filtra_por_estado_y_por_mis_casos(client, limpiar):
    advisor_id, headers = _asesor_nuevo(client, limpiar)
    sesion = _conversacion_de_usuario(client, limpiar)
    conv_id = sesion["conversation"]["conversation_id"]
    _tomar(client, headers, conv_id)

    en_atencion = client.get(
        "/advisor/conversations", params={"status": "IN_ATTENTION"}, headers=headers
    ).json()["conversations"]
    assert conv_id in {c["conversation_id"] for c in en_atencion}

    mias = client.get("/advisor/conversations", params={"mine": "true"}, headers=headers).json()
    assert [c["conversation_id"] for c in mias["conversations"]] == [conv_id]
    assert mias["conversations"][0]["user_name"] == "Jorge", "contexto del usuario (RF-033)"

    pendientes = client.get(
        "/advisor/conversations", params={"status": "PENDING_ADVISOR"}, headers=headers
    ).json()["conversations"]
    assert conv_id not in {c["conversation_id"] for c in pendientes}


def test_sin_filtro_los_pendientes_van_antes_que_los_en_atencion(client, limpiar):
    _, headers = _asesor_nuevo(client, limpiar)
    todas = client.get("/advisor/conversations", headers=headers).json()["conversations"]
    estados = [c["status"] for c in todas]
    assert "PENDING_ADVISOR" in estados, "el seed conv_002 esta pendiente"
    corte = estados.index("IN_ATTENTION") if "IN_ATTENTION" in estados else len(estados)
    assert all(s == "PENDING_ADVISOR" for s in estados[:corte])
    assert "PENDING_ADVISOR" not in estados[corte:]


def test_un_estado_invalido_es_422(client, limpiar):
    _, headers = _asesor_nuevo(client, limpiar)
    response = client.get("/advisor/conversations", params={"status": "X"}, headers=headers)
    assert response.status_code == 422


# ───────────────────────────── AC-A4: toma atomica ─────────────────────────────


def test_tomar_apaga_el_bot_asigna_y_deja_la_nota_en_el_hilo(client, limpiar):
    advisor_id, headers = _asesor_nuevo(client, limpiar, name="Ana Prueba")
    sesion = _conversacion_de_usuario(client, limpiar)
    conv_id = sesion["conversation"]["conversation_id"]

    tomada = _tomar(client, headers, conv_id)
    assert tomada["status"] == "IN_ATTENTION"
    assert tomada["assigned_advisor_id"] == advisor_id
    assert tomada["bot_enabled"] is False

    hilo = client.get(f"/advisor/conversations/{conv_id}/messages", headers=headers).json()
    nota = hilo["messages"][-1]
    assert nota["sender_type"] == "SYSTEM" and nota["content"] == "ADVISOR_ASSIGNED"
    assert nota["metadata"] == {"advisor_id": advisor_id, "advisor_name": "Ana Prueba"}

    # El widget la ve en su sondeo, como las notas de sistema de Intercom.
    del_usuario = client.get(
        f"/chat/conversations/{conv_id}/messages",
        headers={"Authorization": f"Bearer {sesion['token']}"},
    ).json()["messages"]
    assert del_usuario[-1]["content"] == "ADVISOR_ASSIGNED"


def test_solo_un_asesor_gana_la_toma_y_el_otro_recibe_el_estado_actual(client, limpiar):
    primero, h1 = _asesor_nuevo(client, limpiar)
    segundo, h2 = _asesor_nuevo(client, limpiar)
    sesion = _conversacion_de_usuario(client, limpiar)
    conv_id = sesion["conversation"]["conversation_id"]

    _tomar(client, h1, conv_id)
    rebote = client.post(f"/advisor/conversations/{conv_id}/take", headers=h2)

    assert rebote.status_code == 409
    assert rebote.json()["detail"]["conversation"]["assigned_advisor_id"] == primero
    # Idempotente para el que ya la tiene.
    assert _tomar(client, h1, conv_id)["assigned_advisor_id"] == primero


# ───────────────────────────── AC-A5: responder ─────────────────────────────


def test_responder_sin_tomar_es_409(client, limpiar):
    _, headers = _asesor_nuevo(client, limpiar)
    sesion = _conversacion_de_usuario(client, limpiar)
    response = client.post(
        f"/advisor/conversations/{sesion['conversation']['conversation_id']}/messages",
        json={"client_message_id": "adv-" + uuid.uuid4().hex, "content": "hola"},
        headers=headers,
    )
    assert response.status_code == 409


def test_la_respuesta_nace_entregada_firmada_y_no_se_duplica_al_reintentar(client, limpiar):
    advisor_id, headers = _asesor_nuevo(client, limpiar, name="Ana Prueba")
    sesion = _conversacion_de_usuario(client, limpiar)
    conv_id = sesion["conversation"]["conversation_id"]
    _tomar(client, headers, conv_id)

    url = f"/advisor/conversations/{conv_id}/messages"
    cuerpo = {"client_message_id": "adv-" + uuid.uuid4().hex, "content": "  Hola Jorge, te ayudo  "}
    primera = client.post(url, json=cuerpo, headers=headers)
    reintento = client.post(url, json=cuerpo, headers=headers)

    assert primera.status_code == 201 and primera.json()["duplicate"] is False
    mensaje = primera.json()["message"]
    assert mensaje["sender_type"] == "ADVISOR" and mensaje["sender_id"] == advisor_id
    assert mensaje["status"] == "DELIVERED" and mensaje["content"] == "Hola Jorge, te ayudo"
    assert mensaje["metadata"] == {"sender_name": "Ana Prueba"}
    assert reintento.json()["duplicate"] is True
    assert reintento.json()["message"]["message_id"] == mensaje["message_id"]

    del_usuario = client.get(
        f"/chat/conversations/{conv_id}/messages",
        headers={"Authorization": f"Bearer {sesion['token']}"},
    ).json()["messages"]
    del_asesor = [m["content"] for m in del_usuario if m["sender_type"] == "ADVISOR"]
    assert del_asesor == ["Hola Jorge, te ayudo"]


def test_el_largo_maximo_aplica_tambien_al_asesor(client, limpiar, monkeypatch):
    _, headers = _asesor_nuevo(client, limpiar)
    sesion = _conversacion_de_usuario(client, limpiar)
    conv_id = sesion["conversation"]["conversation_id"]
    _tomar(client, headers, conv_id)
    monkeypatch.setenv("MAX_MESSAGE_CHARS", "10")
    reset_settings()
    response = client.post(
        f"/advisor/conversations/{conv_id}/messages",
        json={"client_message_id": "adv-" + uuid.uuid4().hex, "content": "x" * 11},
        headers=headers,
    )
    assert response.status_code == 422


# ───────────────────────────── AC-A6: hilo y no leidos ─────────────────────────────


def test_el_hilo_entrega_los_ultimos_20_y_pagina_hacia_atras(client, limpiar, monkeypatch):
    # Sin rate limit: aqui se prueba la paginacion, y 25 mensajes seguidos superan de sobra el
    # tope por minuto de D-005 (que tiene sus propias pruebas en tests/test_guardrails.py).
    monkeypatch.setenv("MAX_MESSAGES_PER_MINUTE", "0")
    reset_settings()
    _, headers = _asesor_nuevo(client, limpiar)
    sesion = _conversacion_de_usuario(client, limpiar)
    conv_id = sesion["conversation"]["conversation_id"]
    for i in range(25):
        _usuario_escribe(client, sesion, f"m{i:02d}")

    pagina = client.get(f"/advisor/conversations/{conv_id}/messages", headers=headers).json()
    assert [m["content"] for m in pagina["messages"]] == [f"m{i:02d}" for i in range(5, 25)]
    assert pagina["has_more"] is True

    anterior = client.get(
        f"/advisor/conversations/{conv_id}/messages",
        params={"before": pagina["next_before"]},
        headers=headers,
    ).json()
    assert [m["content"] for m in anterior["messages"]] == [f"m{i:02d}" for i in range(5)]
    assert anterior["has_more"] is False

    nuevo = _usuario_escribe(client, sesion, "m25")
    sondeo = client.get(
        f"/advisor/conversations/{conv_id}/messages",
        params={"after": pagina["next_after"]},
        headers=headers,
    ).json()
    assert [m["message_id"] for m in sondeo["messages"]] == [nuevo["message_id"]]


def test_abrir_el_hilo_consume_los_no_leidos(client, limpiar):
    _, headers = _asesor_nuevo(client, limpiar)
    sesion = _conversacion_de_usuario(client, limpiar)
    conv_id = sesion["conversation"]["conversation_id"]
    _tomar(client, headers, conv_id)  # bot apagado: lo que escriba el usuario cuenta (RF-035)
    _usuario_escribe(client, sesion, "sigo esperando")
    _usuario_escribe(client, sesion, "hola?")

    antes = client.get(f"/advisor/conversations/{conv_id}", headers=headers).json()
    assert antes["unread_count"] == 2

    hilo = client.get(f"/advisor/conversations/{conv_id}/messages", headers=headers).json()
    assert hilo["conversation"]["unread_count"] == 0
    despues = client.get(f"/advisor/conversations/{conv_id}", headers=headers).json()
    assert despues["unread_count"] == 0


def test_before_y_after_son_excluyentes(client, limpiar):
    _, headers = _asesor_nuevo(client, limpiar)
    sesion = _conversacion_de_usuario(client, limpiar)
    response = client.get(
        f"/advisor/conversations/{sesion['conversation']['conversation_id']}/messages",
        params={"before": "a", "after": "b"},
        headers=headers,
    )
    assert response.status_code == 422


# ───────────────────────────── AC-A7: cerrar el caso ─────────────────────────────


def test_cerrar_exige_ser_el_asignado(client, limpiar):
    _, h1 = _asesor_nuevo(client, limpiar)
    _, h2 = _asesor_nuevo(client, limpiar)
    sesion = _conversacion_de_usuario(client, limpiar)
    conv_id = sesion["conversation"]["conversation_id"]
    _tomar(client, h1, conv_id)

    assert client.post(f"/advisor/conversations/{conv_id}/close", headers=h2).status_code == 409


def test_cerrar_deja_la_nota_y_devuelve_la_conversacion_al_bot(client, limpiar):
    advisor_id, headers = _asesor_nuevo(client, limpiar)
    sesion = _conversacion_de_usuario(client, limpiar)
    conv_id = sesion["conversation"]["conversation_id"]
    _tomar(client, headers, conv_id)
    _usuario_escribe(client, sesion, "gracias")

    cerrada = client.post(f"/advisor/conversations/{conv_id}/close", headers=headers).json()
    assert cerrada["status"] == "BOT_ATTENDING" and cerrada["bot_enabled"] is True
    assert cerrada["assigned_advisor_id"] is None and cerrada["unread_count"] == 0
    assert cerrada["closed_at"] is None, "D-003: la conversacion no se cierra"

    del_usuario = client.get(
        f"/chat/conversations/{conv_id}/messages",
        headers={"Authorization": f"Bearer {sesion['token']}"},
    ).json()["messages"]
    assert del_usuario[-1]["sender_type"] == "SYSTEM"
    assert del_usuario[-1]["content"] == "TICKET_CLOSED"

    # Vuelve a ser tomable por cualquiera (la asignacion se libero).
    assert _tomar(client, headers, conv_id)["assigned_advisor_id"] == advisor_id
