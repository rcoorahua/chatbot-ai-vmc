"""Casos y handoff con formulario (D-029, cerrada 2026-09-02; D-031 el 2026-09-05) — RF-022,
RF-024, RF-025, RF-031, RF-035, RNF-005.

Criterios:
  AC-H1  anonimo: solo FAQ (D-031). POST /handoff y GET /handoff/form son 409, nada cambia
         en su conversacion, y la sesion trae el enlace para crear cuenta
  AC-H2  la conversacion anonima nace con TTL y sus mensajes lo heredan (sin chats muertos)
  AC-H3  autenticado: el formulario abre un CASO (PENDING_ADVISOR, bot apagado, asunto,
         transcripcion del hilo) y el hilo sigue BOT_ATTENDING con el bot encendido y la nota
         CASE_OPENED; el correo del JWT se usa sin pedirlo, y si falta se exige en el formulario
  AC-H4  tope de casos abiertos → 409; GET /chat/conversations lista el hilo primero y los
         casos por recencia; el caso de OTRO usuario (o para un anonimo) es 403
  AC-H5  cerrar un caso lo deja CLOSED y de solo lectura (mensaje → 409, nota
         CONVERSATION_CLOSED) y fuera de "mis casos"; un hilo (autenticado o anonimo) sigue
         volviendo al bot (AC-A7)
  AC-H6  GET .../messages sin cursor entrega los ULTIMOS N con el estado de la conversacion y
         `has_more`; `before` pagina hacia atras

El authorizer del asesor se simula con el middleware de dev (backend/api/dev_auth.py) y el
encolado a SQS con un doble, como en tests/test_advisor_api.py y tests/test_chat_api.py.
"""

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

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
        # Derivar abre un ticket (RF-023): sin borrarlo aqui queda en el GSI de estado y
        # rompe las pruebas de lectura que cuentan los pendientes del dataset base.
        for item in tablas["tickets"].query(
            IndexName="gsi1_conversation",
            KeyConditionExpression=Key("conversation_id").eq(conversation_id),
        )["Items"]:
            tablas["tickets"].delete_item(Key={"ticket_id": item["ticket_id"]})
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


# ───────────────────────────── AC-H1: el anonimo no deriva (D-031) ─────────────────────────────


def test_el_anonimo_no_puede_pedir_asesor(client, limpiar):
    """D-031: al visitante no se le pide contacto ni se le abre nada; el widget lo manda a
    crear cuenta con el enlace que viaja en la sesion."""
    sesion = _sesion(client, limpiar)
    assert sesion["links"]["signup"] == get_settings().vmc_signup_url

    assert _handoff(client, sesion, email="ana@example.test").status_code == 409
    assert _formulario(client, sesion).status_code == 409

    actual = client.get(
        f"/chat/conversations/{sesion['conversation']['conversation_id']}", headers=_auth(sesion)
    ).json()
    assert actual["status"] == "BOT_ATTENDING" and actual["bot_enabled"] is True
    assert _mensajes(client, sesion)["messages"] == [], "no quedo ninguna nota ni formulario"


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
    assert detalle["user_email"] == "jorge@otro.test", "el correo del formulario es el del caso"


# ───────────────────────────── AC-H4: tope, listado y autorizacion ─────────────────────────────


def test_el_tope_de_casos_abiertos_es_409(client, limpiar, monkeypatch):
    monkeypatch.setenv("MAX_OPEN_CASES_PER_USER", "1")
    reset_settings()
    sesion = _sesion(client, limpiar, autenticado=True)

    assert _handoff(client, sesion, limpiar).status_code == 201
    segundo = _handoff(client, sesion, limpiar, subject="Otro asunto distinto")
    assert segundo.status_code == 409
    assert "1 casos abiertos" in segundo.json()["detail"]


def test_seis_handoffs_concurrentes_con_limite_cinco_dejan_como_maximo_cinco(
    client, limpiar, monkeypatch, tablas
):
    """DETAILS.md §4.5 / Paso 6: el limite se hace cumplir con un ADD condicionado en la
    MISMA transaccion que crea el caso — no con list_open_cases (GSI) antes de crear, que es
    check-then-act y deja pasar mas de N bajo carrera real."""
    monkeypatch.setenv("MAX_OPEN_CASES_PER_USER", "5")
    reset_settings()
    sesion = _sesion(client, limpiar, autenticado=True)
    hilo_id = sesion["conversation"]["conversation_id"]
    user_id = tablas["conversations"].get_item(Key={"conversation_id": hilo_id})["Item"][
        "user_id"
    ]
    limpiar.limite(f"OPEN_CASES#USER#{user_id}")

    n = 8
    barrera = threading.Barrier(n)

    def intentar(i):
        barrera.wait(timeout=10)
        return _handoff(client, sesion, subject=f"Caso concurrente {i}")

    with ThreadPoolExecutor(max_workers=n) as pool:
        resultados = [f.result() for f in [pool.submit(intentar, i) for i in range(n)]]

    exitosos = [r for r in resultados if r.status_code == 201]
    rechazados = [r for r in resultados if r.status_code == 409]
    assert len(exitosos) == 5, [r.status_code for r in resultados]
    assert len(rechazados) == n - 5
    for r in exitosos:
        limpiar.conversacion(r.json()["conversation"]["conversation_id"])

    abiertos = [
        c
        for c in tablas["conversations"].query(
            IndexName="gsi1_user", KeyConditionExpression=Key("user_id").eq(user_id)
        )["Items"]
        if c.get("kind") == "CASE" and c.get("status") != "CLOSED"
    ]
    assert len(abiertos) == 5, "una sola fila fisica por caso exitoso, no mas de cinco"


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


@pytest.mark.parametrize("autenticado", [True, False], ids=["autenticado", "anonimo"])
def test_cerrar_un_hilo_lo_devuelve_al_bot(client, limpiar, autenticado):
    """AC-A7 vale para todo hilo con el bot: un asesor que lo tomo (D-022, intervencion
    proactiva) y lo cierra lo devuelve al bot; no queda CLOSED. Al anonimo lo termina cerrar
    la pestaña (D-031), no el asesor."""
    sesion = _sesion(client, limpiar, autenticado=autenticado)
    hilo_id = sesion["conversation"]["conversation_id"]
    _, headers = _asesor_nuevo(client, limpiar)

    cerrado = _tomar_y_cerrar(client, headers, hilo_id)
    assert cerrado["status"] == "BOT_ATTENDING" and cerrado["bot_enabled"] is True
    assert cerrado["closed_at"] is None
    assert _mensajes(client, sesion)["messages"][-1]["content"] == "TICKET_CLOSED"
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


# ────────────── DETAILS.md §4.9 / Paso 11: tope de sesiones anonimas por IP ──────────────


def test_con_el_tope_por_ip_la_segunda_sesion_del_dia_es_429(client, limpiar, monkeypatch):
    ip = f"10.3.{uuid.uuid4().int % 256}.{uuid.uuid4().int % 256}"
    monkeypatch.setattr(chat_router, "_client_ip", lambda request: ip)
    monkeypatch.setenv("ANON_SESSIONS_PER_IP_PER_DAY", "1")
    reset_settings()
    limpiar.limite(f"SESSION#IP#{quota.hash_ip(ip)}")

    primera = client.post("/chat/sessions", json={})
    assert primera.status_code == 201
    limpiar.conversacion(primera.json()["conversation"]["conversation_id"])

    segunda = client.post("/chat/sessions", json={})
    assert segunda.status_code == 429 and segunda.headers["Retry-After"]


def test_el_tope_de_sesiones_no_aplica_al_autenticado(client, limpiar, monkeypatch):
    # El autenticado ya se cuenta por user_id (D-027); un JWT de VMC valido no es facil de
    # falsificar en volumen, asi que no comparte el tope por IP del anonimo.
    ip = f"10.4.{uuid.uuid4().int % 256}.{uuid.uuid4().int % 256}"
    monkeypatch.setattr(chat_router, "_client_ip", lambda request: ip)
    monkeypatch.setenv("ANON_SESSIONS_PER_IP_PER_DAY", "1")
    reset_settings()
    limpiar.limite(f"SESSION#IP#{quota.hash_ip(ip)}")

    anonima = client.post("/chat/sessions", json={})
    assert anonima.status_code == 201
    limpiar.conversacion(anonima.json()["conversation"]["conversation_id"])

    autenticada = _sesion(client, limpiar, autenticado=True)
    assert autenticada


# ───────────── AC-H9: la tarjeta de formulario para el badge "Asesor humano" (D-030) ─────────────


def _formulario(client, sesion, conversation_id=None):
    conversation_id = conversation_id or sesion["conversation"]["conversation_id"]
    return client.get(
        f"/chat/conversations/{conversation_id}/handoff/form", headers=_auth(sesion)
    )


def test_el_badge_recibe_la_misma_tarjeta_que_ofrece_el_bot(client, limpiar):
    """Con correo en el JWT: solo asunto y detalle; sin correo, se pide primero. Un solo
    paso. Sin pasar por el bot ni por ningun modelo."""
    con_correo = _sesion(client, limpiar, autenticado=True)
    response = _formulario(client, con_correo)
    assert response.status_code == 200, response.text
    spec = response.json()["interaction"]
    assert spec["type"] == "HANDOFF_FORM"
    assert [f["name"] for f in spec["fields"]] == ["subject", "detail"]

    sin_correo = _sesion(client, limpiar, autenticado=True, email=None)
    spec = _formulario(client, sin_correo).json()["interaction"]
    assert [f["name"] for f in spec["fields"]] == ["email", "subject", "detail"]


def test_la_tarjeta_es_409_cuando_no_se_puede_pedir_asesor(client, limpiar):
    """Desde un caso (ya esta con el equipo) no se pide otro asesor."""
    sesion = _sesion(client, limpiar, autenticado=True)
    caso_id = _handoff(client, sesion, limpiar).json()["conversation"]["conversation_id"]

    response = _formulario(client, sesion, caso_id)

    assert response.status_code == 409, response.text


def test_la_tarjeta_de_otro_usuario_es_403(client, limpiar):
    uno = _sesion(client, limpiar, autenticado=True)
    otro = _sesion(client, limpiar, autenticado=True)

    response = _formulario(client, otro, uno["conversation"]["conversation_id"])

    assert response.status_code == 403
