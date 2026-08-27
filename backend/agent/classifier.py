"""Clasificacion de intencion en dos etapas (RF-015/016).

Etapa 1  reglas deterministas (`heuristics.classify_by_rules`): resuelven los mensajes
         inequivocos sin gastar una llamada y calculan la señal de frustracion.
Etapa 2  modelo del tier FAST para el resto.

El orden es la optimizacion de costo principal del pipeline: el trafico que resuelve la etapa 1
no paga tokens (skill `llm-cost-optimizer`). `ClassificationResult` lleva de que etapa salio la
decision para que AIUsage pueda medir esa proporcion en produccion, que es el dato que dice si
las reglas valen lo que cuestan en mantenimiento.

TD-008: hoy clasifica Gemini (tier FAST). T9 preveia Haiku y sigue siendo el plan B si el golden
set de intents muestra que el routing no alcanza — el cambio es de una linea en `core/llm.py`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from backend.agent import prompts
from backend.agent.heuristics import classify_by_rules
from backend.agent.intents import Intent
from backend.core.llm import LLMError, ModelTier, empty_usage, get_client

# Tope de salida: la respuesta esperada es "<intent>ADVISOR</intent>", unos 10 tokens. El margen
# cubre que el modelo agregue espacios o un salto de linea, sin dejar espacio a divagar.
_MAX_OUTPUT_TOKENS = 24

# El mensaje se recorta antes de enviarlo: para elegir entre cuatro etiquetas, el arranque
# sobra, y un mensaje enorme solo suma costo y superficie de inyeccion.
_MAX_MESSAGE_CHARS = 500
_MAX_CONTEXT_CHARS = 400

_INTENT_PATTERN = re.compile(r"<intent>\s*([A-Z_]+)\s*</intent>", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class ClassificationResult:
    """Intencion decidida y como se llego a ella.

    `rule` viene informada solo cuando decidio la etapa 1; nombra el motivo (`legal_threat`,
    `catalog_search`...) y es lo que despues explica al asesor por que se derivo el caso.
    `usage` y `latency_ms` van en cero en ese caso, que es justamente lo que se quiere medir.
    """

    intent: Intent
    source: str  # "rules" | "model" | "fallback"
    rule: str | None = None
    model: str | None = None
    usage: dict[str, int] | None = None
    latency_ms: int = 0
    frustration_hint: bool = False


def classify(message: str, last_assistant_message: str | None = None) -> ClassificationResult:
    """Devuelve la intencion del mensaje. Nunca lanza: sin decision segura, FAQ.

    FAQ es el fallback porque es la ruta que sigue conversando. Caer en ADVISOR ante cualquier
    fallo llenaria la bandeja de los asesores con incidencias tecnicas, y caer en OTHER cortaria
    la conversacion de un usuario legitimo.
    """
    text = (message or "").strip()
    if not text:
        return ClassificationResult(intent=Intent.FAQ, source="fallback")

    heuristic = classify_by_rules(text)
    if heuristic.intent is not None:
        return ClassificationResult(
            intent=heuristic.intent,
            source="rules",
            rule=heuristic.rule,
            usage=empty_usage(),
            frustration_hint=heuristic.frustration_hint,
        )

    try:
        return _classify_with_model(text, last_assistant_message, heuristic.frustration_hint)
    except LLMError:
        # El detalle del fallo lo registra quien orquesta (worker), que es quien tiene el
        # contexto de la conversacion; aqui solo garantizamos que el usuario reciba respuesta.
        return ClassificationResult(
            intent=Intent.FAQ,
            source="fallback",
            frustration_hint=heuristic.frustration_hint,
        )


def _classify_with_model(
    message: str,
    last_assistant_message: str | None,
    frustration_hint: bool,
) -> ClassificationResult:
    system_prompt = _build_system_prompt(last_assistant_message, frustration_hint)

    response = get_client().generate(
        tier=ModelTier.FAST,
        system=system_prompt,
        messages=[{"role": "user", "content": message[:_MAX_MESSAGE_CHARS]}],
        max_output_tokens=_MAX_OUTPUT_TOKENS,
        # Sin aleatoriedad: la misma consulta debe enrutar igual siempre, o el golden set mide
        # ruido en vez de comportamiento.
        temperature=0.0,
    )

    return ClassificationResult(
        intent=_parse_intent(response.text),
        source="model",
        model=response.model,
        usage=response.usage,
        latency_ms=response.latency_ms,
        frustration_hint=frustration_hint,
    )


def _build_system_prompt(last_assistant_message: str | None, frustration_hint: bool) -> str:
    """Arma el prompt manteniendo el bloque estable al inicio, que es lo que se cachea."""
    parts = [prompts.CLASSIFIER_SYSTEM_PROMPT]
    if frustration_hint:
        parts.append(prompts.CLASSIFIER_FRUSTRATION_HINT)
    if last_assistant_message and last_assistant_message.strip():
        parts.append(
            prompts.CLASSIFIER_CONTEXT_TEMPLATE.format(
                last_assistant_message=last_assistant_message.strip()[:_MAX_CONTEXT_CHARS],
                faq=Intent.FAQ,
            )
        )
    return "".join(parts)


def _parse_intent(raw: str) -> Intent:
    """Extrae la etiqueta. Cualquier salida inesperada cae en FAQ.

    Solo se acepta la etiqueta dentro de <intent>; no se busca el nombre suelto en el texto
    porque un modelo que ignoro el formato tambien pudo mencionar varias categorias, y quedarse
    con la primera que aparezca convierte un fallo evidente en un enrutado silencioso y erroneo.
    """
    match = _INTENT_PATTERN.search(raw or "")
    if not match:
        return Intent.FAQ
    try:
        return Intent(match.group(1).upper())
    except ValueError:
        return Intent.FAQ
