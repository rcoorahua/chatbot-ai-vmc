"""Logging estructurado por entorno (RNF-006).

Politica (Aaron, 2026-08-28): **dev y stage detallados** (DEBUG, con vista previa del contenido
de los mensajes) y **prod sobrio** (INFO, sin contenido ni PII: solo ids, decisiones y metricas).
Todo se ajusta por variables de entorno (`LOG_LEVEL`, `LOG_CONTENT`, `LOG_FORMAT`) sin desplegar
codigo, que es lo que hace falta en un incidente.

Formato: **JSON en Lambda** (CloudWatch Logs Insights filtra por campo: `fields intent, source |
filter event = "ai.execution"`) y **texto legible en local**. Convencion de los eventos del
pipeline: el mensaje del log es el NOMBRE del evento (`ai.execution`, `ai.handoff`...) y los
datos van en `extra={...}`, que el formateador vuelca completo. Asi un evento nuevo no exige
tocar el formateador y las consultas en CloudWatch no dependen de parsear texto.

Por que no se loguea el contenido en prod: regla 7 de security-guidance y RF-052. Un log es
otra copia del dato, sin TTL ni control de acceso fino; `content_preview` devuelve solo la
longitud cuando `LOG_CONTENT` esta apagado.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

from backend.core.config import get_settings

# Atributos propios de LogRecord: todo lo que no este aqui vino en `extra` y es un campo nuestro.
_STANDARD_ATTRS = set(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {
    "message", "asctime", "taskName",
}

_NOISY_LIBRARIES = ("botocore", "boto3", "urllib3", "httpx", "httpcore", "google", "pinecone")


def _extras(record: logging.LogRecord) -> dict[str, Any]:
    return {
        key: value
        for key, value in record.__dict__.items()
        if key not in _STANDARD_ATTRS and not key.startswith("_")
    }


class JsonFormatter(logging.Formatter):
    """Una linea JSON por evento. `default=str` cubre Decimal, enums y datetimes sin que un tipo
    raro en `extra` tumbe el log (perder un log no debe romper el pipeline)."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        payload.update(_extras(record))
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


class TextFormatter(logging.Formatter):
    """Para la terminal: hora corta, nivel, evento y los campos como `clave=valor`."""

    def format(self, record: logging.LogRecord) -> str:
        line = (
            f"{self.formatTime(record, '%H:%M:%S')} {record.levelname:<7} "
            f"{record.name}: {record.getMessage()}"
        )
        extras = " ".join(f"{key}={_compact(value)}" for key, value in _extras(record).items())
        if extras:
            line += "  " + extras
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return line


def _compact(value: Any) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return json.dumps(text, ensure_ascii=False) if " " in text or "=" in text else text


_configured = False


def configure_logging(force: bool = False) -> None:
    """Instala nivel y formato segun el entorno. Idempotente: las entradas (api, workers,
    scripts) la llaman al importar y la Lambda tibia no la repite."""
    global _configured
    if _configured and not force:
        return
    settings = get_settings()
    level = logging.getLevelName(settings.effective_log_level)
    formatter = JsonFormatter() if settings.effective_log_format == "json" else TextFormatter()

    root = logging.getLogger()
    if not root.handlers:
        root.addHandler(logging.StreamHandler(sys.stdout))
    # En Lambda el runtime ya instalo un handler con su propio formato: se le cambia el
    # formateador en vez de agregar otro, que duplicaria cada linea en CloudWatch.
    for handler in root.handlers:
        handler.setFormatter(formatter)
    root.setLevel(level)
    # Las librerias HTTP en DEBUG escriben cabeceras y cuerpos completos (con credenciales):
    # nunca bajan de WARNING, sea cual sea el nivel nuestro.
    for name in _NOISY_LIBRARIES:
        logging.getLogger(name).setLevel(max(level, logging.WARNING))
    _configured = True


def reset_logging() -> None:
    """Para tests que cambian el entorno y necesitan reconfigurar."""
    global _configured
    _configured = False


def content_preview(text: str | None, limit: int = 120) -> str | None:
    """Vista previa de un mensaje para los logs.

    Con `LOG_CONTENT` apagado (prod por defecto) devuelve solo la longitud: el contenido de un
    chat es dato del usuario y un log no es lugar para otra copia (RF-052, security-guidance 7).
    """
    if text is None:
        return None
    if not get_settings().effective_log_content:
        return f"<{len(text)} chars>"
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[:limit] + "…"
