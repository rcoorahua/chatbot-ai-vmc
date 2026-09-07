"""Contrato de `Message.metadata` entre el backend y el widget (y el frontend del asesor).

Las claves y los tipos de interaccion son un contrato de tres puntas (worker que escribe,
API que persiste y valida, widget que dibuja), asi que viven en `core`, importables desde el
dominio y desde las integraciones por igual. Antes cada modulo escribia el literal
`"interaction"` por su cuenta y `"LINKS"` no tenia constante (auditoria 2026-09-06).

    metadata = {
        "interaction": {"type": <InteractionType>, ...},   # botones, formulario, enlaces
        "sources":     [{"title", "url"}, ...],             # chip de fuente (D-030)
        "rag_query":   "...",                               # la consulta que dio evidencia
        "form_response": {...}, "transcript": [...],        # lo que envio el formulario (D-029)
        "sender_name": "...",                               # firma del asesor
    }
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

INTERACTION = "interaction"
TYPE = "type"
OPTIONS = "options"
SOURCES = "sources"
RAG_QUERY = "rag_query"
FORM_RESPONSE = "form_response"
TRANSCRIPT = "transcript"
SENDER_NAME = "sender_name"


class InteractionType(StrEnum):
    """Lo que el widget sabe dibujar bajo un mensaje del bot (`widget/subastin.js`)."""

    QUICK_REPLIES = "QUICK_REPLIES"  # botones de un flujo guiado (D-028)
    RELATED_QUESTIONS = "RELATED_QUESTIONS"  # preguntas hermanas + "Contactar asesor" (D-030/031)
    HANDOFF_FORM = "HANDOFF_FORM"  # tarjeta de formulario de asesor (D-029)
    LINKS = "LINKS"  # enlaces con pinta de boton, p. ej. "Iniciar sesion" (D-031)


def interaction_of(metadata: dict[str, Any] | None) -> dict[str, Any] | None:
    """La interaccion del mensaje, o None. Tolera metadata ausente o malformada: la escribe
    el servidor, pero en el mensaje del USUARIO viene del cliente y nunca se confia en el."""
    value = (metadata or {}).get(INTERACTION)
    return value if isinstance(value, dict) else None


def interaction_type(metadata: dict[str, Any] | None) -> str | None:
    interaction = interaction_of(metadata)
    return interaction.get(TYPE) if interaction else None


def with_interaction(kind: InteractionType | str, **fields: Any) -> dict[str, Any]:
    """La metadata de un mensaje del bot que lleva una interaccion (mas los campos propios
    del tipo: `options`, `fields`, `flow_version`...)."""
    return {INTERACTION: {TYPE: str(kind), **fields}}


def choice(label: str, value: str, **extra: Any) -> dict[str, Any]:
    """Una opcion de QUICK_REPLIES / RELATED_QUESTIONS: lo que se ve y lo que se envia."""
    return {"label": label, "value": value, **extra}


def link(label: str, url: str) -> dict[str, Any]:
    """Una opcion de LINKS: el widget solo dibuja `http(s)`."""
    return {"label": label, "url": url}
