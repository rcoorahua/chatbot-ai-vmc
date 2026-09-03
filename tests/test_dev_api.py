"""Rutas de observabilidad `/dev/*` (backend/api/routers/dev.py) — RNF-006.

Criterios:
  AC-O1  con DEV_OBSERVABILITY encendido, la sesion ve las ejecuciones IA de SU conversacion,
         con totales de tokens y costo y el estado de la conversacion
  AC-O2  otra conversacion = 403; sin token = 401 (mismo contrato que /chat)
  AC-O3  con DEV_OBSERVABILITY=0 (prod) la ruta responde 404: no existe hacia afuera
  AC-O4  cada ejecucion registrada emite un evento `ai.execution` en el log, sin contenido
  AC-O5  una ejecucion con RAG expone tema/score/fuente por fragmento recuperado
"""

import logging

import pytest
from boto3.dynamodb.conditions import Key
from fastapi.testclient import TestClient

from backend.agent import usage
from backend.api.main import app
from backend.core.config import reset_settings

pytestmark = pytest.mark.usefixtures("entorno_dynamo")


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def limpiar(tablas):
    ids: list[str] = []
    yield ids.append
    for conversation_id in ids:
        for tabla, sk in (("messages", "message_key"), ("ai_usage", "execution_key")):
            for item in tablas[tabla].query(
                KeyConditionExpression=Key("conversation_id").eq(conversation_id)
            )["Items"]:
                tablas[tabla].delete_item(
                    Key={"conversation_id": conversation_id, sk: item[sk]}
                )
        tablas["conversations"].delete_item(Key={"conversation_id": conversation_id})


@pytest.fixture(autouse=True)
def _observabilidad_encendida(monkeypatch):
    monkeypatch.setenv("DEV_OBSERVABILITY", "1")
    reset_settings()
    yield
    reset_settings()


def _sesion(client, limpiar) -> dict:
    response = client.post("/chat/sessions", json={})
    assert response.status_code == 201, response.text
    data = response.json()
    limpiar(data["conversation"]["conversation_id"])
    return data


def _auth(sesion: dict) -> dict:
    return {"Authorization": f"Bearer {sesion['token']}"}


def _registrar(conversation_id: str, *, pagada: bool) -> None:
    usage.record_execution(
        conversation_id=conversation_id,
        message_id="m-1",
        execution_type=usage.RESPONSE if pagada else usage.CLASSIFICATION,
        intent="FAQ",
        source="model" if pagada else "advisor_request",
        provider="GOOGLE" if pagada else usage.NO_PROVIDER,
        model="gemini-3.6-flash" if pagada else None,
        usage={"input": 900, "output": 120, "cached_read": 0, "cached_creation": 0}
        if pagada
        else None,
        estimated_cost_usd=0.001125 if pagada else 0.0,
        latency_ms=1450 if pagada else 0,
        rag_used=pagada,
        rag_results_count=3 if pagada else None,
        rag_fragments=[
            {
                "topic": "¿Cuánto es la comisión?",
                "score": 0.87123,
                "source_url": "https://centro-de-ayuda-vmc.vercel.app/comision",
            },
            {"topic": "Fee por el uso de pasarela", "score": 0.844, "source_url": ""},
            # Por debajo del umbral: no fue evidencia, pero la consola lo muestra igual.
            {"topic": "Retiro de saldo", "score": 0.81, "source_url": "", "relevant": False},
        ]
        if pagada
        else None,
        rag_min_score=0.84 if pagada else None,
    )


def test_la_sesion_ve_sus_ejecuciones_con_totales(client, limpiar, caplog):
    sesion = _sesion(client, limpiar)
    conversation_id = sesion["conversation"]["conversation_id"]
    with caplog.at_level(logging.INFO, logger="backend.agent.usage"):
        _registrar(conversation_id, pagada=False)
        _registrar(conversation_id, pagada=True)

    response = client.get(f"/dev/conversations/{conversation_id}/ai-usage", headers=_auth(sesion))

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["conversation"]["status"] == "BOT_ATTENDING"
    assert data["conversation"]["bot_enabled"] is True
    assert [e["execution_type"] for e in data["executions"]] == ["RESPONSE", "CLASSIFICATION"], (
        "de la mas reciente a la mas antigua"
    )
    pagada = data["executions"][0]
    assert pagada["model"] == "gemini-3.6-flash" and pagada["input_tokens"] == 900
    assert pagada["estimated_cost_usd"] == pytest.approx(0.001125)

    # AC-O5: la consola necesita saber QUE trajo el RAG, no solo cuantos fragmentos —
    # incluidos los hits bajo el umbral, marcados como no relevantes.
    assert [f["topic"] for f in pagada["rag_fragments"]] == [
        "¿Cuánto es la comisión?",
        "Fee por el uso de pasarela",
        "Retiro de saldo",
    ]
    assert pagada["rag_fragments"][0]["score"] == pytest.approx(0.8712)
    assert pagada["rag_fragments"][0]["source_url"].startswith("https://")
    assert pagada["rag_fragments"][1]["source_url"] == ""
    assert [f["relevant"] for f in pagada["rag_fragments"]] == [True, True, False]
    assert pagada["rag_min_score"] == pytest.approx(0.84)
    sin_rag = data["executions"][1]
    assert sin_rag["rag_fragments"] == [], "la clasificacion no toca RAG"
    assert data["totals"] == {
        "executions": 2,
        "ai_calls": 1,
        "free_executions": 1,
        "input_tokens": 900,
        "output_tokens": 120,
        "cached_tokens": 0,
        "estimated_cost_usd": pytest.approx(0.001125),
        "total_latency_ms": 1450,
    }

    eventos = [r for r in caplog.records if r.getMessage() == "ai.execution"]
    assert len(eventos) == 2, "AC-O4: un evento por ejecucion"
    assert eventos[1].source == "model" and eventos[1].estimated_cost_usd == 0.001125
    assert not hasattr(eventos[1], "content"), "el log lleva metricas, nunca el texto"


def test_otra_conversacion_es_403_y_sin_token_401(client, limpiar):
    sesion = _sesion(client, limpiar)
    otra = _sesion(client, limpiar)

    ajena = client.get(
        f"/dev/conversations/{otra['conversation']['conversation_id']}/ai-usage",
        headers=_auth(sesion),
    )
    assert ajena.status_code == 403

    sin_token = client.get(
        f"/dev/conversations/{sesion['conversation']['conversation_id']}/ai-usage"
    )
    assert sin_token.status_code == 401


def test_apagada_la_ruta_no_existe(client, limpiar, monkeypatch):
    sesion = _sesion(client, limpiar)
    monkeypatch.setenv("DEV_OBSERVABILITY", "0")
    reset_settings()

    response = client.get(
        f"/dev/conversations/{sesion['conversation']['conversation_id']}/ai-usage",
        headers=_auth(sesion),
    )
    assert response.status_code == 404, "en prod la ruta no se revela ni con sesion valida"


# ───────────────────── Inspector de tablas y colas (pestañas de test.html) ─────────────────────
# AC-O6: con STAGE=dev, /dev/tables lista las 5 tablas y el scan de una devuelve items y claves.
# AC-O7: fuera de dev NO EXISTEN (404), aunque DEV_OBSERVABILITY este encendido — el gate es mas
#        estricto que el de ai-usage porque un scan vuelca datos de TODOS los usuarios.


def test_el_inspector_lista_las_cinco_tablas(client):
    response = client.get("/dev/tables")
    assert response.status_code == 200
    tables = response.json()["tables"]
    assert [t["key"] for t in tables] == [
        "conversations", "messages", "tickets", "advisors", "ai-usage"
    ]
    assert all("count" in t or "error" in t for t in tables)


def test_el_scan_devuelve_items_y_claves(client):
    response = client.get("/dev/tables/messages?limit=5")
    assert response.status_code == 200
    data = response.json()
    assert data["key_attributes"] == ["conversation_id", "message_key"]
    assert data["count"] <= 5
    assert isinstance(data["items"], list)


def test_una_tabla_desconocida_es_404(client):
    assert client.get("/dev/tables/usuarios").status_code == 404


def test_el_inspector_no_existe_fuera_de_dev(client, monkeypatch):
    """El gate estricto: en stage, ai-usage sigue vivo pero el inspector no."""
    monkeypatch.setenv("STAGE", "stage")
    reset_settings()
    try:
        assert client.get("/dev/tables").status_code == 404
        assert client.get("/dev/tables/messages").status_code == 404
        assert client.get("/dev/queues").status_code == 404
    finally:
        reset_settings()


def test_el_inspector_de_colas_responde_estructura(client):
    """No exige localstack arriba: una cola caida se reporta como error, nunca como 500."""
    response = client.get("/dev/queues")
    assert response.status_code == 200
    data = response.json()
    assert [q["key"] for q in data["queues"]] == ["ai-jobs", "notifications"]
    for queue in data["queues"]:
        assert ("visible" in queue and "peek" in queue) or "error" in queue
    assert isinstance(data["recent_jobs"], list)
