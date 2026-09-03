"""Redaccion de la respuesta automatica con el tier ANSWER (RF-020).

Recibe el mensaje, la ventana reciente de conversacion (~20 mensajes, RF-013) y la evidencia ya
recuperada por RAG o HERALD. No recupera nada por su cuenta: quien compone el flujo es el worker
(`workers/ai_worker.py`), de modo que este modulo no importa dominio ni otras integraciones.

Contrato central (RF-018): sin evidencia no se redacta. La respuesta es un texto fijo que ofrece
un asesor, no una generacion — pedirle al modelo que responda "sin datos" es justo el escenario
donde inventa. Por eso `write_answer` devuelve `has_evidence`, que es lo que el worker usa para
decidir si dispara el handoff.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from backend.agent import guardrails, prompts
from backend.core.config import get_settings
from backend.core.llm import LLMError, ModelTier, empty_usage, get_client

logger = logging.getLogger(__name__)

# El tope de salida vive en Settings (`ai_answer_max_tokens`, D-005 cerrada 2026-08-28): la
# brevedad la pide el prompt, el tope la garantiza cuando el modelo se extiende igual.

# Presupuesto de evidencia. Recortar por caracteres es una aproximacion deliberada: contar
# tokens exige una llamada extra al proveedor y el objetivo aqui es acotar el costo, no medirlo
# al detalle. ~4 caracteres por token es la relacion habitual en español.
_MAX_CONTEXT_CHARS = 12_000

# La ventana de conversacion se recorta al final: los mensajes recientes son los que sostienen
# el hilo. El valor sale de RF-013 (~20 mensajes) y la estrategia de resumen es D-004.
_MAX_HISTORY_MESSAGES = 20


@dataclass(frozen=True, slots=True)
class WriterResult:
    """Respuesta redactada y lo que el worker necesita para decidir y registrar.

    `has_evidence` en False significa que no se llamo al modelo y `text` es el mensaje fijo de
    derivacion: el worker debe iniciar handoff (RF-018), no reintentar.
    """

    text: str
    has_evidence: bool
    model: str | None = None
    usage: dict[str, int] | None = None
    latency_ms: int = 0
    # Nombre de la violacion cuando el guardrail de salida rechazo lo generado (D-024). Va
    # aparte de `has_evidence` para que AIUsage distinga "no habia evidencia" de "habia, pero
    # el modelo se salio de ella": son problemas distintos con arreglos distintos.
    guardrail: str | None = None


def write_answer(
    message: str,
    context_fragments: list[str],
    history: list[dict[str, str]] | None = None,
) -> WriterResult:
    """Redacta la respuesta a partir de la evidencia recuperada.

    `context_fragments` son los textos ya recuperados (chunks de Pinecone, resultado de HERALD).
    Una lista vacia no es un caso de error: es la señal de que no hay con que responder.
    """
    fragments = [
        # Los angulos se neutralizan porque el fragmento va DENTRO del system prompt: un
        # "</contexto>" en el corpus (o en un enlace) cerraria el bloque y lo que siguiera
        # pasaria por instruccion.
        guardrails.neutralize_tags(fragment.strip())
        for fragment in (context_fragments or [])
        if fragment.strip()
    ]
    if not fragments:
        return WriterResult(
            text=prompts.WRITER_NO_EVIDENCE_FALLBACK,
            has_evidence=False,
            usage=empty_usage(),
        )

    system_prompt = prompts.WRITER_SYSTEM_PROMPT + prompts.WRITER_CONTEXT_TEMPLATE.format(
        context=_build_context(fragments)
    )

    try:
        response = get_client().generate(
            tier=ModelTier.ANSWER,
            system=system_prompt,
            messages=_build_messages(message, history),
            max_output_tokens=get_settings().ai_answer_max_tokens,
            # Temperatura baja, no cero: la respuesta debe ceñirse a la evidencia, pero cero
            # produce un fraseo rigido y repetitivo entre conversaciones parecidas.
            temperature=0.2,
        )
    except LLMError as exc:
        # Un fallo del proveedor no puede convertirse en una respuesta inventada ni en un error
        # crudo al usuario: se trata igual que la falta de evidencia y el worker deriva.
        # PERO se loguea SIEMPRE: tragarse la causa hizo que un error de configuracion
        # ("Thinking level MINIMAL is not supported", 2026-09-01) pareciera "no hay evidencia"
        # durante horas — RAG traia fragmentos buenos y todo caia al texto fijo sin una pista.
        logger.warning("ai.writer.llm_error", extra={"error": str(exc)})
        return WriterResult(
            text=prompts.WRITER_NO_EVIDENCE_FALLBACK,
            has_evidence=False,
            usage=empty_usage(),
        )

    text = guardrails.tidy(response.text)
    if not text:
        # Respuesta vacia (corte por tope de tokens o filtro del proveedor): no hay nada que
        # mostrar, y el fallback es preferible a un mensaje en blanco.
        return WriterResult(
            text=prompts.WRITER_NO_EVIDENCE_FALLBACK,
            has_evidence=False,
            model=response.model,
            usage=response.usage,
            latency_ms=response.latency_ms,
        )

    # Guardrail de salida (D-024): lo que el prompt pide, aqui se verifica. Una cifra o un
    # enlace que no esten en la evidencia, o una fuga del prompt, no llegan al usuario: se
    # tratan como falta de evidencia y el worker deriva (RF-018).
    verdict = guardrails.check_output(text, fragments, message)
    if not verdict.ok:
        return WriterResult(
            text=prompts.WRITER_NO_EVIDENCE_FALLBACK,
            has_evidence=False,
            model=response.model,
            usage=response.usage,
            latency_ms=response.latency_ms,
            guardrail=verdict.violation,
        )

    return WriterResult(
        text=text,
        has_evidence=True,
        model=response.model,
        usage=response.usage,
        latency_ms=response.latency_ms,
    )


def _build_context(fragments: list[str]) -> str:
    """Une los fragmentos numerados hasta agotar el presupuesto de caracteres.

    Se numeran para que el modelo pueda distinguirlos entre si, y se corta por fragmento
    completo en vez de a mitad: media frase de evidencia es peor que un fragmento menos.
    """
    parts: list[str] = []
    remaining = _MAX_CONTEXT_CHARS
    for index, fragment in enumerate(fragments, start=1):
        block = f"[{index}] {fragment}"
        if len(block) > remaining:
            break
        parts.append(block)
        remaining -= len(block)
    return "\n\n".join(parts)


def _build_messages(message: str, history: list[dict[str, str]] | None) -> list[dict[str, str]]:
    """Ventana reciente mas el mensaje actual, descartando roles que el proveedor no acepta."""
    messages: list[dict[str, str]] = []
    for turn in (history or [])[-_MAX_HISTORY_MESSAGES:]:
        if turn.get("role") in ("user", "assistant") and turn.get("content"):
            messages.append(
                {"role": turn["role"], "content": guardrails.neutralize_tags(turn["content"])}
            )
    messages.append({"role": "user", "content": guardrails.neutralize_tags(message)})
    return messages
