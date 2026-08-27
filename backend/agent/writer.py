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

from dataclasses import dataclass

from backend.agent import prompts
from backend.core.llm import LLMError, ModelTier, empty_usage, get_client

# Tope de salida: caben tres o cuatro frases con margen. La brevedad la pide el prompt, pero el
# tope es lo que la garantiza cuando el modelo se extiende de todas formas.
# TODO D-005: mover a Settings cuando se cierren los guardrails cuantitativos; RNF-007 exige
# que los limites sean configurables y no literales en el codigo.
_MAX_OUTPUT_TOKENS = 600

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


def write_answer(
    message: str,
    context_fragments: list[str],
    history: list[dict[str, str]] | None = None,
) -> WriterResult:
    """Redacta la respuesta a partir de la evidencia recuperada.

    `context_fragments` son los textos ya recuperados (chunks de Pinecone, resultado de HERALD).
    Una lista vacia no es un caso de error: es la señal de que no hay con que responder.
    """
    fragments = [fragment.strip() for fragment in (context_fragments or []) if fragment.strip()]
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
            max_output_tokens=_MAX_OUTPUT_TOKENS,
            # Temperatura baja, no cero: la respuesta debe ceñirse a la evidencia, pero cero
            # produce un fraseo rigido y repetitivo entre conversaciones parecidas.
            temperature=0.2,
        )
    except LLMError:
        # Un fallo del proveedor no puede convertirse en una respuesta inventada ni en un error
        # crudo al usuario: se trata igual que la falta de evidencia y el worker deriva.
        return WriterResult(
            text=prompts.WRITER_NO_EVIDENCE_FALLBACK,
            has_evidence=False,
            usage=empty_usage(),
        )

    text = response.text.strip()
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
            messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": message})
    return messages
