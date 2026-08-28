"""Rutas de observabilidad `/dev/*` (backend/api/routers/dev.py) — RNF-006.

Criterios:
  AC-O1  con DEV_OBSERVABILITY encendido, la sesion ve las ejecuciones IA de SU conversacion,
         con totales de tokens y costo y el estado de la conversacion
  AC-O2  otra conversacion = 403; sin token = 401 (mismo contrato que /chat)
  AC-O3  con DEV_OBSERVABILITY=0 (prod) la ruta responde 404: no existe hacia afuera
  AC-O4  cada ejecucion registrada emite un evento `ai.execution` en el log, sin contenido
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
        model="gemini-3.7-flash" if pagada else None,
        usage={"input": 900, "output": 120, "cached_read": 0, "cached_creation": 0}
        if pagada
        else None,
        estimated_cost_usd=0.001125 if pagada else 0.0,
        latency_ms=1450 if pagada else 0,
        rag_used=pagada,
        rag_results_count=3 if pagada else None,
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
    assert pagada["model"] == "gemini-3.7-flash" and pagada["input_tokens"] == 900
    assert pagada["estimated_cost_usd"] == pytest.approx(0.001125)
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
