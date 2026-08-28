"""Logging por entorno (backend/core/observability.py) — RNF-006.

Criterios:
  AC-L1  dev/stage: DEBUG con vista previa del contenido; prod: INFO y SIN contenido (RF-052)
  AC-L2  LOG_LEVEL / LOG_CONTENT pisan el default del stage
  AC-L3  el formateador JSON vuelca los campos de `extra` como claves de primer nivel; el de
         texto los compacta como clave=valor
  AC-L4  configure_logging fija el nivel del root y nunca deja las librerias HTTP en DEBUG
"""

import json
import logging
from decimal import Decimal

import pytest

from backend.core import observability
from backend.core.config import get_settings, reset_settings


@pytest.fixture
def entorno(monkeypatch):
    # Se fijan VACIAS, no se borran: borrarlas del proceso no basta porque pydantic tambien lee
    # el `.env` del desarrollador, y ahi estas variables suelen estar puestas (dev detallado).
    # Vacia equivale a "sin fijar" por el validador `_empty_keeps_default` de core/config.py,
    # que es justo el caso que este test cubre: decidir por STAGE.
    for variable in ("LOG_LEVEL", "LOG_CONTENT", "LOG_FORMAT", "DEV_OBSERVABILITY"):
        monkeypatch.setenv(variable, "")

    def fijar(stage: str, **extra: str):
        monkeypatch.setenv("STAGE", stage)
        for key, value in extra.items():
            monkeypatch.setenv(key, value)
        reset_settings()
        return get_settings()

    yield fijar
    reset_settings()
    observability.reset_logging()
    observability.configure_logging(force=True)


def test_dev_es_detallado_y_prod_sobrio(entorno):
    dev = entorno("dev")
    assert dev.effective_log_level == "DEBUG"
    assert dev.effective_log_content is True
    assert dev.dev_observability_enabled is True
    assert observability.content_preview("hola   mundo") == "hola mundo"
    assert observability.content_preview("x" * 200).endswith("…")

    prod = entorno("prod")
    assert prod.effective_log_level == "INFO"
    assert prod.effective_log_content is False
    assert prod.dev_observability_enabled is False
    assert observability.content_preview("hola mundo") == "<10 chars>", "en prod solo el largo"
    assert observability.content_preview(None) is None


def test_las_variables_pisan_el_default_del_stage(entorno):
    settings = entorno("prod", LOG_LEVEL="debug", LOG_CONTENT="1", DEV_OBSERVABILITY="1")
    assert settings.effective_log_level == "DEBUG"
    assert settings.effective_log_content is True
    assert settings.dev_observability_enabled is True
    settings = entorno("dev", LOG_CONTENT="0", DEV_OBSERVABILITY="0", LOG_FORMAT="json")
    assert settings.effective_log_content is False
    assert settings.dev_observability_enabled is False
    assert settings.effective_log_format == "json"


def _record(**extra):
    record = logging.LogRecord("subastin", logging.INFO, "", 0, "ai.execution", None, None)
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_el_formato_json_vuelca_los_campos_extra():
    salida = observability.JsonFormatter().format(
        _record(intent="FAQ", estimated_cost_usd=Decimal("0.001"), rag_used=True)
    )
    datos = json.loads(salida)
    assert datos["event"] == "ai.execution" and datos["level"] == "INFO"
    assert datos["intent"] == "FAQ" and datos["rag_used"] is True
    assert datos["estimated_cost_usd"] == "0.001", "Decimal no rompe el log: se serializa como str"


def test_el_formato_texto_compacta_los_campos():
    salida = observability.TextFormatter().format(_record(intent="FAQ", text="hola mundo"))
    assert "ai.execution" in salida
    assert "intent=FAQ" in salida and 'text="hola mundo"' in salida


def test_configure_logging_fija_nivel_y_acalla_librerias(entorno):
    entorno("dev")
    observability.reset_logging()
    observability.configure_logging()

    assert logging.getLogger().level == logging.DEBUG
    assert logging.getLogger("botocore").level == logging.WARNING
    assert logging.getLogger("httpx").level == logging.WARNING
    assert all(
        isinstance(handler.formatter, observability.TextFormatter)
        for handler in logging.getLogger().handlers
    )
