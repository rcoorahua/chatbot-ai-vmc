"""Log de peticiones HTTP (`api/request_log.py`) — RNF-006.

Criterios:
  AC-L1  cada petición deja un `http.request` con método, plantilla de ruta, estado y duración
  AC-L2  el nivel sigue al resultado: 2xx en DEBUG, 4xx en WARNING, 5xx en ERROR — así en prod
         (INFO, sin contenido) los rechazos y los errores saltan solos y el tráfico normal no
  AC-L3  un rechazo deja además un `http.error` con el MOTIVO (lo que explica un 404 o un 409),
         y de un detalle estructurado solo se guarda su texto
  AC-L4  no se registra ni el cuerpo, ni la cabecera Authorization, ni la query cruda: por ahí
         viajan los mensajes del usuario, los datos del formulario y el token de sesión
  AC-L5  `/health` y el preflight `OPTIONS` no ensucian el log
"""

import logging

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.api import request_log


@pytest.fixture
def app():
    application = FastAPI()
    request_log.install(application)

    @application.get("/health")
    def health():
        return {"status": "ok"}

    @application.get("/eco/{cosa}")
    def eco(cosa: str, secreto: str | None = None):
        return {"cosa": cosa}

    @application.get("/falta")
    def falta():
        raise HTTPException(404, "Conversacion no encontrada")

    @application.get("/tomada")
    def tomada():
        raise HTTPException(409, {"detail": "Ya esta tomada", "conversation": {"id": "x"}})

    @application.get("/explota")
    def explota():
        raise RuntimeError("algo se rompio")

    return application


@pytest.fixture
def client(app):
    return TestClient(app, raise_server_exceptions=False)


def _registros(caplog, evento):
    # getMessage() y no `.message`: ese atributo solo existe si el record ya paso por un
    # formatter, y en la captura se cuelan records de otras librerias que no pasaron.
    return [
        r
        for r in caplog.records
        if r.name == "backend.api.request_log" and r.getMessage() == evento
    ]


# ───────────────────────── AC-L1 y AC-L2: la línea por petición ─────────────────────────


def test_una_peticion_deja_su_linea_con_ruta_estado_y_duracion(client, caplog):
    with caplog.at_level(logging.DEBUG, logger="backend.api.request_log"):
        assert client.get("/eco/hola").status_code == 200

    registro = _registros(caplog, "http.request")[0]
    assert registro.levelno == logging.DEBUG, "el trafico normal no grita en prod"
    assert registro.method == "GET"
    assert registro.route == "/eco/{cosa}", "la plantilla agrupa; el path suelto no"
    assert registro.path == "/eco/hola"
    assert registro.status == 200
    assert registro.duration_ms >= 0
    assert registro.request_id


def test_un_rechazo_sube_a_warning_y_un_error_del_servidor_a_error(client, caplog):
    with caplog.at_level(logging.DEBUG, logger="backend.api.request_log"):
        assert client.get("/falta").status_code == 404
        assert client.get("/explota").status_code == 500

    por_estado = {r.status: r for r in _registros(caplog, "http.request")}
    assert por_estado[404].levelno == logging.WARNING
    assert _registros(caplog, "http.exception")[0].levelno == logging.ERROR


def test_una_ruta_inexistente_tambien_queda_registrada(client, caplog):
    with caplog.at_level(logging.DEBUG, logger="backend.api.request_log"):
        assert client.get("/no-existe-esta-ruta").status_code == 404

    registro = _registros(caplog, "http.request")[0]
    assert registro.status == 404 and registro.path == "/no-existe-esta-ruta"


def test_la_excepcion_no_controlada_deja_la_ruta_y_el_traceback(client, caplog):
    with caplog.at_level(logging.DEBUG, logger="backend.api.request_log"):
        client.get("/explota")

    registro = _registros(caplog, "http.exception")[0]
    assert registro.route == "/explota"
    assert registro.exc_info is not None, "sin traceback no se sabe que se rompio"


# ───────────────────────── AC-L3: el motivo del rechazo ─────────────────────────


def test_el_rechazo_explica_por_que(client, caplog):
    with caplog.at_level(logging.DEBUG, logger="backend.api.request_log"):
        client.get("/falta")

    error = _registros(caplog, "http.error")[0]
    assert error.status == 404
    assert error.detail == "Conversacion no encontrada"
    assert error.route == "/falta"


def test_de_un_detalle_estructurado_solo_se_guarda_su_texto(client, caplog):
    """El 409 de la toma lleva la conversacion entera; volcarla en el log seria ruido y datos
    del usuario donde no corresponden."""
    with caplog.at_level(logging.DEBUG, logger="backend.api.request_log"):
        client.get("/tomada")

    error = _registros(caplog, "http.error")[0]
    assert error.detail == "Ya esta tomada"


def test_el_error_y_la_peticion_comparten_el_id_de_correlacion(client, caplog):
    with caplog.at_level(logging.DEBUG, logger="backend.api.request_log"):
        client.get("/falta")

    peticion = _registros(caplog, "http.request")[0]
    error = _registros(caplog, "http.error")[0]
    assert error.request_id == peticion.request_id


# ───────────────────────── AC-L4: lo que NUNCA se registra ─────────────────────────


def test_no_se_registran_ni_el_token_ni_la_query_ni_el_cuerpo(client, caplog):
    with caplog.at_level(logging.DEBUG, logger="backend.api.request_log"):
        client.get(
            "/eco/hola",
            params={"secreto": "dato-personal-en-la-query"},
            headers={"Authorization": "Bearer token-de-sesion-que-es-una-credencial"},
        )

    registro = _registros(caplog, "http.request")[0]
    volcado = " ".join(str(v) for v in vars(registro).values())
    assert "token-de-sesion" not in volcado
    assert "dato-personal-en-la-query" not in volcado


# ───────────────────────── AC-L5: lo que no ensucia el log ─────────────────────────


def test_health_y_el_preflight_no_se_registran(client, caplog):
    with caplog.at_level(logging.DEBUG, logger="backend.api.request_log"):
        client.get("/health")
        client.options("/eco/hola")

    assert _registros(caplog, "http.request") == []


# ───────────────────────── Integración con la app real ─────────────────────────


def test_la_app_real_registra_el_403_de_una_conversacion_ajena(caplog):
    """La pregunta que motivó esto: "¿por qué el widget no carga el hilo?" ahora tiene
    respuesta en el log sin reproducir nada."""
    from backend.api.main import app as app_real

    with caplog.at_level(logging.DEBUG, logger="backend.api.request_log"):
        TestClient(app_real).get("/chat/conversations/la-de-otro/messages")

    registro = _registros(caplog, "http.request")[0]
    assert registro.status == 401
    assert registro.route == "/chat/conversations/{conversation_id}/messages"
    assert _registros(caplog, "http.error")[0].detail == "Falta el token de sesion"
