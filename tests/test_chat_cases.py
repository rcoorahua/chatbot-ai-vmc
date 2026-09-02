"""Casos y handoff con formulario (D-029, cerrada 2026-09-02) — RF-003, RF-022, RF-024,
RF-025, RF-031, RF-035, RNF-005.

Criterios:
  AC-H1  anonimo: el formulario exige nombre y correo (422 con `field`), telefono opcional; al
         enviarlo su conversacion pasa a PENDING_ADVISOR con el bot apagado, guarda asunto y
         contacto (los ve el asesor), deja FORM_RESPONSE + nota HANDOFF_REQUESTED +
         confirmacion fija, y cuenta 1 no leido; un segundo envio es 409
  AC-H2  la conversacion anonima nace con TTL y sus mensajes lo heredan (sin chats muertos)
  AC-H3  autenticado: el formulario abre un CASO (PENDING_ADVISOR, bot apagado, asunto,
         transcripcion del hilo) y el hilo sigue BOT_ATTENDING con el bot encendido y la nota
         CASE_OPENED; el correo del JWT se usa sin pedirlo, y si falta se exige en el formulario
  AC-H4  tope de casos abiertos → 409; GET /chat/conversations lista el hilo primero y los
         casos por recencia; el caso de OTRO usuario (o para un anonimo) es 403
  AC-H5  cerrar un caso o la conversacion anonima los deja CLOSED y de solo lectura (mensaje
         → 409, nota CONVERSATION_CLOSED) y fuera de "mis casos"; el hilo del autenticado sigue
         volviendo al bot (AC-A7)
  AC-H6  GET .../messages sin cursor entrega los ULTIMOS N con el estado de la conversacion y
         `has_more`; `before` pagina hacia atras
  AC-H7  con el tope por IP encendido, la segunda solicitud anonima del dia desde la misma IP
         es 429; con el tope en 0 no se frena nada

El authorizer del asesor se simula con el middleware de dev (backend/api/dev_auth.py) y el
encolado a SQS con un doble, como en tests/test_advisor_api.py y tests/test_chat_api.py.
"""

import uuid

import pytest
from boto3.dynamodb.conditions import Key
from fastapi.testclient import TestClient

from backend.agent import prompts, quota
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
    monkeypatch.setenv("MAX_MESSAGES_PER_MINUTE", "0")
    reset_settings()
    monkeypatch.setattr(chat_router.jobs, "enqueue_ai_job", lambda job: None)
    yield TestClient(dev_auth.DevCognitoAuthorizer(app))
    reset_settings()


@pytest.fixture
def limpiar(tablas):
    conversaciones: list[str] = []
    asesores: list[str] = []
    limites: list[str] = []

    class Registro:
        conversacion = staticmethod(conversaciones.append)
        asesor = staticmethod(asesores.append)
        limite = staticmethod(limites.append)

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
    for limit_key in limites:
        for item in tablas["rate_limits"].query(
            KeyConditionExpression=Key("limit_key").eq(limit_key)
        )["Items"]:
            tablas["rate_limits"].delete_item(
                Key={"limit_key": limit_key, "window": item["window"]}
            )


# ───────────────────────────────────── Helpers ─────────────────────────────────────


def _jwt_vmc(user_id: str, **claims) -> str:
    payload = {"sub": user_id, "exp": epoch_seconds() + 600, **claims}
    return auth.sign_jwt(payload, get_settings().vmc_identity_secret)


def _sesion(client, limpiar, *, autenticado=False, email="jorge@example.test") -> dict:
    body = {}
    if autenticado:
        claims = {"name": "Jorge"}
        if email:
            claims["email"] = email
        body["user_jwt"] = _jwt_vmc("vmc_" + uuid.uuid4().hex[:8], **claims)
    response = client.post("/chat/sessions", json=body)
    assert response.status_code == 201, response.text
    sesion = response.json()
    limpiar.conversacion(sesion["conversation"]["conversation_id"])
    return sesion


def _auth(sesion: dict) -> dict:
    return {"Authorization": f"Bearer {sesion['token']}"}


def _escribe(client, sesion, texto="hola", conversation_id=None):
    conversation_id = conversation_id or sesion["conversation"]["conversation_id"]
    return client.post(
        f"/chat/conversations/{conversation_id}/messages",
        json={"client_message_id": "cli-" + uuid.uuid4().hex, "content": texto},
        headers=_auth(sesion),
    )


FORMULARIO = {"subject": "Problema con mi puja", "detail": "No me deja ofertar en la subasta."}
CONTACTO = {"name": "Ana Torres", "email": "ana@example.test"}


def _handoff(client, sesion, limpiar=None, **campos):
    response = client.post(
        f"/chat/conversations/{sesion['conversation']['conversation_id']}/handoff",
        json={**FORMULARIO, **campos},
        headers=_auth(sesion),
    )
    if response.status_code == 201 and limpiar is not None:
        limpiar.conversacion(response.json()["conversation"]["conversation_id"])
    return response


def _mensajes(client, sesion, conversation_id=None, **params) -> dict:
    conversation_id = conversation_id or sesion["conversation"]["conversation_id"]
    response = client.get(
        f"/chat/conversations/{conversation_id}/messages", params=params, headers=_auth(sesion)
    )
    assert response.status_code == 200, response.text
    return response.json()


def _asesor_nuevo(client, limpiar) -> tuple[str, dict]:
    sub = "sub-test-" + uuid.uuid4().hex[:8]
    payload = {"sub": sub, "token_use": "id", "exp": epoch_seconds() + 600, "name": "Ana P."}
    headers = {"Authorization": f"Bearer {auth.sign_jwt(payload, DEV_SECRET)}"}
    me = client.get("/advisor/me", headers=headers)
    assert me.status_code == 200, me.text
    limpiar.asesor(me.json()["advisor_id"])
    return me.json()["advisor_id"], headers


def _tomar_y_cerrar(client, headers, conversation_id) -> dict:
    tomada = client.post(f"/advisor/conversations/{conversation_id}/take", headers=headers)
    assert tomada.status_code == 200, tomada.text
    response = client.post(f"/advisor/conversations/{conversation_id}/close", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


# ───────────────────────────── AC-H1: el anonimo deriva con contacto ─────────────────────────────


def test_el_anonimo_debe_dejar_nombre_y_correo(client, limpiar):
    sesion = _sesion(client, limpiar)

    sin_nombre = _handoff(client, sesion, email="ana@example.test")
    assert sin_nombre.status_code == 422 and sin_nombre.json()["detail"]["field"] == "name"

    mal_correo = _handoff(client, sesion, name="Ana", email="ana-arroba")
    assert mal_correo.status_code == 422 and mal_correo.json()["detail"]["field"] == "email"

    mal_telefono = _handoff(client, sesion, **CONTACTO, phone="abc")
    assert mal_telefono.status_code == 422 and mal_telefono.json()["detail"]["field"] == "phone"

    actual = client.get(
        f"/chat/conversations/{sesion['conversation']['conversation_id']}", headers=_auth(sesion)
    ).json()
    assert actual["status"] == "BOT_ATTENDING", "nada cambio con formularios invalidos"


def test_el_anonimo_deriva_en_el_sitio_y_el_asesor_ve_el_contacto(client, limpiar):
    sesion = _sesion(client, limpiar)
    conversation_id = sesion["conversation"]["conversation_id"]

    respuesta = _handoff(client, sesion, **CONTACTO, phone="+51 999 888 777")
    assert respuesta.status_code == 201, respuesta.text
    derivada = respuesta.json()["conversation"]
    assert derivada["conversation_id"] == conversation_id, "anonimo: no hay caso aparte"
    assert derivada["status"] == "PENDING_ADVISOR" and derivada["bot_enabled"] is False
    assert derivada["kind"] == "THREAD" and derivada["title"] == FORMULARIO["subject"]

    hilo = _mensajes(client, sesion)
    assert hilo["conversation"]["status"] == "PENDING_ADVISOR"
    ultimos = hilo["messages"][-3:]
    assert [m["message_type"] for m in ultimos] == ["FORM_RESPONSE", "SYSTEM", "TEXT"]
    assert [m["sender_type"] for m in ultimos] == ["USER", "SYSTEM", "BOT"]
    assert "Asunto: Problema con mi puja" in ultimos[0]["content"]
    assert "Correo: ana@example.test" in ultimos[0]["content"]
    assert ultimos[1]["content"] == "HANDOFF_REQUESTED"
    assert ultimos[2]["content"] == prompts.HANDOFF_ANON_CONFIRMATION

    _, headers = _asesor_nuevo(client, limpiar)
    detalle = client.get(f"/advisor/conversations/{conversation_id}", headers=headers).json()
    assert detalle["contact_name"] == "Ana Torres"
    assert detalle["contact_email"] == "ana@example.test"
    assert detalle["contact_phone"] == "+51 999 888 777"
    assert detalle["unread_count"] == 1, "RF-035: el formulario es lo primero que lee el asesor"

    otra_vez = _handoff(client, sesion, **CONTACTO)
    assert otra_vez.status_code == 409


# ───────────────────────────── AC-H2: TTL de la conversacion anonima ─────────────────────────────


def test_la_conversacion_anonima_nace_con_ttl_y_sus_mensajes_lo_heredan(client, limpiar, tablas):
    sesion = _sesion(client, limpiar)
    conversation_id = sesion["conversation"]["conversation_id"]
    assert _escribe(client, sesion, "hola").status_code == 202

    fila = tablas["conversations"].get_item(Key={"conversation_id": conversation_id})["Item"]
    dias = get_settings().anonymous_conversation_ttl_days
    assert dias > 0 and int(fila["expires_at"]) > epoch_seconds() + (dias - 1) * 86400

    mensajes = [
        item
        for item in tablas["messages"].query(
            KeyConditionExpression=Key("conversation_id").eq(conversation_id)
        )["Items"]
        if not str(item["message_key"]).startswith("CMID#")
    ]
    assert mensajes and all(int(m["expires_at"]) == int(fila["expires_at"]) for m in mensajes)


def test_el_hilo_del_autenticado_no_tiene_ttl(client, limpiar, tablas):
    sesion = _sesion(client, limpiar, autenticado=True)
    fila = tablas["conversations"].get_item(
        Key={"conversation_id": sesion["conversation"]["conversation_id"]}
    )["Item"]
    assert "expires_at" not in fila, "D-003: el hilo es permanente; la retencion es D-014"


# ───────────────────────────── AC-H3: el autenticado abre un caso ─────────────────────────────


def test_el_autenticado_abre_un_caso_y_el_hilo_sigue_con_el_bot(client, limpiar):
    sesion = _sesion(client, limpiar, autenticado=True)
    hilo_id = sesion["conversation"]["conversation_id"]
    assert _escribe(client, sesion, "no puedo ofertar").status_code == 202

    respuesta = _handoff(client, sesion, limpiar)
    assert respuesta.status_code == 201, respuesta.text
    caso = respuesta.json()["conversation"]
    assert caso["conversation_id"] != hilo_id
    assert caso["kind"] == "CASE" and caso["status"] == "PENDING_ADVISOR"
    assert caso["bot_enabled"] is False and caso["title"] == FORMULARIO["subject"]

    del_caso = _mensajes(client, sesion, caso["conversation_id"])["messages"]
    assert [m["content"] for m in del_caso][0] == "CASE_OPENED"
    assert del_caso[1]["message_type"] == "FORM_RESPONSE"
    assert "Correo:" not in del_caso[1]["content"], "el correo vino en el JWT, no se pide"
    transcripcion = del_caso[1]["metadata"]["transcript"]
    assert any(t["content"] == "no puedo ofertar" for t in transcripcion)
    assert del_caso[2]["content"] == prompts.HANDOFF_CASE_CONFIRMATION

    hilo = _mensajes(client, sesion)
    assert hilo["conversation"]["status"] == "BOT_ATTENDING"
    assert hilo["conversation"]["bot_enabled"] is True, "escalar no apaga el hilo del bot"
    assert hilo["messages"][-1]["content"] == "CASE_OPENED"
    assert hilo["messages"][-1]["metadata"]["case_id"] == caso["conversation_id"]

    _, headers = _asesor_nuevo(client, limpiar)
    detalle = client.get(
        f"/advisor/conversations/{caso['conversation_id']}", headers=headers
    ).json()
    assert detalle["user_email"] == "jorge@example.test"
    assert detalle["source_conversation_id"] == hilo_id
    assert detalle["unread_count"] == 1


def test_el_autenticado_sin_correo_en_el_jwt_debe_darlo(client, limpiar):
    sesion = _sesion(client, limpiar, autenticado=True, email=None)

    sin_correo = _handoff(client, sesion, limpiar)
    assert sin_correo.status_code == 422 and sin_correo.json()["detail"]["field"] == "email"

    con_correo = _handoff(client, sesion, limpiar, email="jorge@otro.test")
    assert con_correo.status_code == 201, con_correo.text
    _, headers = _asesor_nuevo(client, limpiar)
    caso_id = con_correo.json()["conversation"]["conversation_id"]
    detalle = client.get(f"/advisor/conversations/{caso_id}", headers=headers).json()
    assert detalle["user_email"] == "jorge@otro.test"
    assert detalle["contact_email"] == "jorge@otro.test"


# ───────────────────────────── AC-H4: tope, listado y autorizacion ─────────────────────────────


def test_el_tope_de_casos_abiertos_es_409(client, limpiar, monkeypatch):
    monkeypatch.setenv("MAX_OPEN_CASES_PER_USER", "1")
    reset_settings()
    sesion = _sesion(client, limpiar, autenticado=True)

    assert _handoff(client, sesion, limpiar).status_code == 201
    segundo = _handoff(client, sesion, limpiar, subject="Otro asunto distinto")
    assert segundo.status_code == 409
    assert "1 casos abiertos" in segundo.json()["detail"]


def test_el_listado_trae_el_hilo_primero_y_los_casos_por_recencia(client, limpiar):
    sesion = _sesion(client, limpiar, autenticado=True)
    hilo_id = sesion["conversation"]["conversation_id"]
    primero = _handoff(client, sesion, limpiar, subject="Primer caso").json()["conversation"]
    segundo = _handoff(client, sesion, limpiar, subject="Segundo caso").json()["conversation"]

    listado = client.get("/chat/conversations", headers=_auth(sesion)).json()["conversations"]

    assert [c["conversation_id"] for c in listado] == [
        hilo_id, segundo["conversation_id"], primero["conversation_id"]
    ]
    assert [c["kind"] for c in listado] == ["THREAD", "CASE", "CASE"]
    assert listado[1]["title"] == "Segundo caso"


def test_el_anonimo_solo_lista_su_conversacion(client, limpiar):
    sesion = _sesion(client, limpiar)
    listado = client.get("/chat/conversations", headers=_auth(sesion)).json()["conversations"]
    assert [c["conversation_id"] for c in listado] == [sesion["conversation"]["conversation_id"]]


def test_el_caso_de_otro_usuario_es_403(client, limpiar):
    ana = _sesion(client, limpiar, autenticado=True)
    caso_id = _handoff(client, ana, limpiar).json()["conversation"]["conversation_id"]
    otro = _sesion(client, limpiar, autenticado=True)
    anonimo = _sesion(client, limpiar)

    for ajeno in (otro, anonimo):
        assert client.get(f"/chat/conversations/{caso_id}", headers=_auth(ajeno)).status_code == 403
        assert (
            client.get(f"/chat/conversations/{caso_id}/messages", headers=_auth(ajeno)).status_code
            == 403
        )
        assert _escribe(client, ajeno, "hola", conversation_id=caso_id).status_code == 403

    assert _escribe(client, ana, "un detalle mas", conversation_id=caso_id).status_code == 202


# ───────────────────────────── AC-H5: cerrar = CLOSED y solo lectura ─────────────────────────────


def test_cerrar_un_caso_lo_deja_cerrado_y_de_solo_lectura(client, limpiar):
    sesion = _sesion(client, limpiar, autenticado=True)
    caso_id = _handoff(client, sesion, limpiar).json()["conversation"]["conversation_id"]
    advisor_id, headers = _asesor_nuevo(client, limpiar)

    cerrado = _tomar_y_cerrar(client, headers, caso_id)
    assert cerrado["status"] == "CLOSED" and cerrado["bot_enabled"] is False
    assert cerrado["closed_at"] and cerrado["closed_by"] == "ADVISOR"
    assert cerrado["assigned_advisor_id"] == advisor_id, "queda como historial"

    del_usuario = _mensajes(client, sesion, caso_id)
    assert del_usuario["conversation"]["status"] == "CLOSED"
    assert del_usuario["messages"][-1]["content"] == "CONVERSATION_CLOSED"
    assert _escribe(client, sesion, "hola?", conversation_id=caso_id).status_code == 409

    mios = client.get(
        "/advisor/conversations", params={"mine": "true"}, headers=headers
    ).json()["conversations"]
    assert caso_id not in [c["conversation_id"] for c in mios]

    # El hilo del bot sigue vivo y puede abrir otro caso.
    hilo = _mensajes(client, sesion)
    assert hilo["conversation"]["status"] == "BOT_ATTENDING"
    assert _handoff(client, sesion, limpiar, subject="Otro caso").status_code == 201


def test_cerrar_la_conversacion_anonima_la_deja_cerrada(client, limpiar):
    sesion = _sesion(client, limpiar)
    conversation_id = sesion["conversation"]["conversation_id"]
    assert _handoff(client, sesion, **CONTACTO).status_code == 201
    _, headers = _asesor_nuevo(client, limpiar)

    cerrado = _tomar_y_cerrar(client, headers, conversation_id)
    assert cerrado["status"] == "CLOSED" and cerrado["closed_at"]
    assert _escribe(client, sesion, "hola?").status_code == 409
    assert _handoff(client, sesion, **CONTACTO).status_code == 409


def test_cerrar_el_hilo_del_autenticado_lo_devuelve_al_bot(client, limpiar):
    """AC-A7 sigue valiendo para el hilo permanente: un asesor que lo tomo (D-022) y lo
    cierra lo devuelve al bot; no queda CLOSED."""
    sesion = _sesion(client, limpiar, autenticado=True)
    hilo_id = sesion["conversation"]["conversation_id"]
    _, headers = _asesor_nuevo(client, limpiar)

    cerrado = _tomar_y_cerrar(client, headers, hilo_id)
    assert cerrado["status"] == "BOT_ATTENDING" and cerrado["bot_enabled"] is True
    assert cerrado["closed_at"] is None
    assert _escribe(client, sesion, "sigo aqui").status_code == 202


# ───────────────────────── AC-H6: ultimos N y paginacion hacia atras ─────────────────────────


def test_sin_cursor_llegan_los_ultimos_y_before_pagina_hacia_atras(client, limpiar):
    sesion = _sesion(client, limpiar)
    for texto in ("uno", "dos", "tres"):
        assert _escribe(client, sesion, texto).status_code == 202

    ultimos = _mensajes(client, sesion, limit=2)
    assert [m["content"] for m in ultimos["messages"]] == ["dos", "tres"]
    assert ultimos["has_more"] is True
    assert ultimos["conversation"]["conversation_id"] == sesion["conversation"]["conversation_id"]

    anteriores = _mensajes(client, sesion, limit=2, before=ultimos["next_before"])
    assert [m["content"] for m in anteriores["messages"]] == ["uno"]
    assert anteriores["has_more"] is False

    nuevos = _mensajes(client, sesion, after=ultimos["next_after"])
    assert nuevos["messages"] == [] and nuevos["next_after"] == ultimos["next_after"]

    ambos = client.get(
        f"/chat/conversations/{sesion['conversation']['conversation_id']}/messages",
        params={"after": "x", "before": "y"},
        headers=_auth(sesion),
    )
    assert ambos.status_code == 422


# ───────────────────────── AC-H7: tope de handoffs anonimos por IP ─────────────────────────


def test_con_el_tope_por_ip_la_segunda_solicitud_del_dia_es_429(client, limpiar, monkeypatch):
    ip = f"10.0.{uuid.uuid4().int % 256}.{uuid.uuid4().int % 256}"
    monkeypatch.setattr(chat_router, "_client_ip", lambda request: ip)
    monkeypatch.setenv("ANON_HANDOFFS_PER_IP_PER_DAY", "1")
    reset_settings()
    limpiar.limite(f"HANDOFF#IP#{quota.hash_ip(ip)}")

    primera = _sesion(client, limpiar)
    assert _handoff(client, primera, **CONTACTO).status_code == 201

    segunda = _sesion(client, limpiar)
    bloqueada = _handoff(client, segunda, **CONTACTO)
    assert bloqueada.status_code == 429 and bloqueada.headers["Retry-After"]
    assert (
        client.get(
            f"/chat/conversations/{segunda['conversation']['conversation_id']}",
            headers=_auth(segunda),
        ).json()["status"]
        == "BOT_ATTENDING"
    )


def test_con_el_tope_en_cero_no_se_cuenta_nada(client, limpiar, monkeypatch, tablas):
    ip = f"10.1.{uuid.uuid4().int % 256}.{uuid.uuid4().int % 256}"
    monkeypatch.setattr(chat_router, "_client_ip", lambda request: ip)
    assert get_settings().anon_handoffs_per_ip_per_day == 0, "dev: apagado, como AI_QUOTA_*"

    for _ in range(2):
        assert _handoff(client, _sesion(client, limpiar), **CONTACTO).status_code == 201
    contados = tablas["rate_limits"].query(
        KeyConditionExpression=Key("limit_key").eq(f"HANDOFF#IP#{quota.hash_ip(ip)}")
    )["Items"]
    assert contados == []
