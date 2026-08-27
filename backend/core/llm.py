"""Capa de acceso a los modelos de lenguaje. Unico modulo que conoce un SDK de IA.

Los llamadores piden un TIER logico (`FAST` para clasificar, `ANSWER` para redactar), nunca un
nombre de modelo: cambiar de modelo o de proveedor es editar el mapa de `_MODELS`, no cazar
literales por el codigo. El uso se devuelve siempre en el mismo dict —
`{input, output, cached_read, cached_creation}` — que es exactamente lo que la tabla AIUsage
necesita persistir, de modo que agregar un proveedor no obliga a migrar datos.

Estado actual (TD-008): un solo proveedor, Gemini, para ambos tiers. La interfaz esta pensada
para que meter Anthropic o Bedrock sea agregar una subclase de `LLMClient` y una entrada en
`_MODELS` — ver el TODO de `TD-008` mas abajo.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ModelTier(StrEnum):
    """Rol de la llamada, no el modelo que la atiende.

    FAST   clasificacion de intencion: salida de pocos tokens, alto volumen (RF-015).
    ANSWER redaccion de la respuesta con evidencia RAG/HERALD (RF-020).
    """

    FAST = "fast"
    ANSWER = "answer"


# Modelo por tier y su precio vigente, en USD por millon de tokens.
#
# El precio se guarda junto al modelo a proposito: `estimated_cost_usd` de AIUsage se calcula
# con el precio del momento de la ejecucion, no con uno recordado despues (regla de la skill
# llm-cost-optimizer). `priced_until` documenta que estos son precios promocionales de Google:
# a partir del 2027-01-01 el Flash de redaccion sube a 1.50/7.50 y hay que actualizar la tabla.
#
# Eleccion (2026-08-27): flash-lite para clasificar porque la tarea es elegir 1 de 4 etiquetas
# y no necesita capacidad de razonamiento; 3.7-flash para redactar porque cuesta lo mismo que
# 3.6-flash y Google lo describe como su Flash mas capaz.
@dataclass(frozen=True, slots=True)
class ModelSpec:
    name: str
    input_usd_per_million: float
    output_usd_per_million: float
    priced_until: str | None = None


_MODELS: dict[ModelTier, ModelSpec] = {
    ModelTier.FAST: ModelSpec(
        name="gemini-3.1-flash-lite",
        input_usd_per_million=0.25,
        output_usd_per_million=1.50,
    ),
    ModelTier.ANSWER: ModelSpec(
        name="gemini-3.7-flash",
        input_usd_per_million=0.75,
        output_usd_per_million=3.75,
        priced_until="2026-12-31",  # desde 2027-01-01: 1.50 / 7.50
    ),
}

# TODO TD-008: hoy Gemini atiende ambos tiers. T9 preveia Haiku (`claude-haiku-4-5`) como
# clasificador y sigue siendo el plan B si el golden set de intents muestra que Gemini no
# alcanza en routing. Migrar el tier FAST es: subclase `AnthropicClient(LLMClient)` con el SDK
# `anthropic`, cambiar la entrada FAST de `_MODELS` y elegir entre API directa o Bedrock
# (TD-002). El resto del codigo no se entera porque solo conoce `ModelTier`.


def empty_usage() -> dict[str, int]:
    """Contadores en cero, con las mismas claves que devuelve cualquier proveedor.

    Existe para que los caminos que no llaman al modelo (heuristicas, cortocircuitos) escriban
    en AIUsage con la misma forma que los que si llaman, y las sumas no tengan que distinguir.
    """
    return {"input": 0, "output": 0, "cached_read": 0, "cached_creation": 0}


@dataclass(frozen=True, slots=True)
class LLMResponse:
    """Respuesta normalizada, independiente del proveedor."""

    text: str
    model: str
    tier: ModelTier
    usage: dict[str, int] = field(default_factory=empty_usage)
    latency_ms: int = 0

    def estimated_cost_usd(self) -> float:
        """Costo de esta llamada con el precio vigente del modelo que la atendio.

        Los tokens cacheados se cobran distinto segun el proveedor; mientras no se active el
        caching (pendiente de D-004, que define el resumen de conversacion) se cuentan como
        input normal, que sobreestima antes que subestimar.
        """
        spec = _MODELS[self.tier]
        billable_input = self.usage["input"] + self.usage["cached_read"]
        return (
            billable_input * spec.input_usd_per_million
            + self.usage["output"] * spec.output_usd_per_million
        ) / 1_000_000


class LLMError(Exception):
    """Error de proveedor ya normalizado, para que quien reintenta no conozca el SDK.

    Las banderas separan lo que se puede reintentar de lo que no: insistir ante una cuota
    agotada o una credencial invalida solo multiplica la latencia antes del mismo fallo.
    """

    def __init__(
        self,
        message: str,
        *,
        provider: str,
        status_code: int | None = None,
        is_rate_limit: bool = False,
        is_connection: bool = False,
        is_fatal: bool = False,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code
        self.is_rate_limit = is_rate_limit
        self.is_connection = is_connection
        self.is_fatal = is_fatal


class LLMClient:
    """Interfaz que implementa cada proveedor."""

    provider: str = "base"

    def generate(
        self,
        *,
        tier: ModelTier,
        system: str,
        messages: list[dict[str, str]],
        max_output_tokens: int,
        temperature: float | None = None,
    ) -> LLMResponse:
        raise NotImplementedError


class GeminiClient(LLMClient):
    """Implementacion sobre el SDK `google-genai`."""

    provider = "gemini"

    def __init__(self, api_key: str) -> None:
        from google import genai

        self._client = genai.Client(api_key=api_key)

    def generate(
        self,
        *,
        tier: ModelTier,
        system: str,
        messages: list[dict[str, str]],
        max_output_tokens: int,
        temperature: float | None = None,
    ) -> LLMResponse:
        from google.genai import errors, types

        spec = _MODELS[tier]
        config: dict[str, Any] = {"max_output_tokens": max_output_tokens}
        if system:
            config["system_instruction"] = system
        if temperature is not None:
            config["temperature"] = temperature

        # Los Gemini 3.x razonan por defecto y esos tokens salen del MISMO presupuesto que
        # max_output_tokens: sin bajarlo, una clasificacion con tope de 24 tokens se gasta el
        # presupuesto pensando y devuelve vacio. Ninguna de nuestras dos tareas necesita
        # razonamiento extendido: clasificar es elegir una etiqueta y redactar es reformular
        # evidencia que ya viene dada.
        config["thinking_config"] = types.ThinkingConfig(thinking_level="minimal")

        started = time.perf_counter()
        try:
            response = self._client.models.generate_content(
                model=spec.name,
                contents=self._to_contents(types, messages),
                config=types.GenerateContentConfig(**config),
            )
        except errors.APIError as exc:
            raise self._normalize(exc) from exc
        latency_ms = int((time.perf_counter() - started) * 1000)

        return LLMResponse(
            text=self._extract_text(response),
            model=spec.name,
            tier=tier,
            usage=self._to_usage(getattr(response, "usage_metadata", None)),
            latency_ms=latency_ms,
        )

    @staticmethod
    def _to_contents(types: Any, messages: list[dict[str, str]]) -> list[Any]:
        """Convierte al formato de Gemini, que nombra `model` al rol del asistente."""
        return [
            types.Content(
                role="model" if message["role"] == "assistant" else "user",
                parts=[types.Part.from_text(text=message["content"])],
            )
            for message in messages
            if message.get("content")
        ]

    @staticmethod
    def _extract_text(response: Any) -> str:
        """Texto de la respuesta, reconstruido desde las partes si hace falta.

        `response.text` viene en None cuando la generacion se corta (tope de tokens, filtro de
        seguridad) aunque haya texto parcial en las partes. Devolver "" en ese caso perderia
        contenido util y, en clasificacion, convertiria una respuesta valida en un fallo.
        """
        text = getattr(response, "text", None)
        if text:
            return text
        parts: list[str] = []
        for candidate in getattr(response, "candidates", None) or []:
            content = getattr(candidate, "content", None)
            for part in getattr(content, "parts", None) or []:
                if getattr(part, "text", None):
                    parts.append(part.text)
        return "".join(parts)

    @staticmethod
    def _to_usage(usage_metadata: Any) -> dict[str, int]:
        """Mapea el uso de Gemini al dict comun.

        Los tokens de razonamiento se facturan como salida aunque no aparezcan en el texto:
        sumarlos evita subestimar el costo en AIUsage.
        """
        if usage_metadata is None:
            return empty_usage()
        thoughts = getattr(usage_metadata, "thoughts_token_count", 0) or 0
        return {
            "input": getattr(usage_metadata, "prompt_token_count", 0) or 0,
            "output": (getattr(usage_metadata, "candidates_token_count", 0) or 0) + thoughts,
            "cached_read": getattr(usage_metadata, "cached_content_token_count", 0) or 0,
            # Gemini no cobra la creacion de cache por token; la clave existe para que el dict
            # tenga la misma forma en todos los proveedores.
            "cached_creation": 0,
        }

    def _normalize(self, exc: Any) -> LLMError:
        code = getattr(exc, "code", None)
        message = str(getattr(exc, "message", "") or exc)
        lowered = message.lower()
        # Un 429 puede ser un pico de trafico (se reintenta) o la cuota del proyecto agotada
        # (reintentar no la devuelve); solo el mensaje los distingue.
        quota_exhausted = any(
            marker in lowered for marker in ("billing", "quota exceeded", "exceeded your current")
        )
        return LLMError(
            message,
            provider=self.provider,
            status_code=code,
            is_rate_limit=(code == 429 and not quota_exhausted),
            is_connection=(code is not None and code >= 500),
            is_fatal=(code in (401, 403) or quota_exhausted),
        )


_client: LLMClient | None = None


def get_client() -> LLMClient:
    """Cliente del proveedor activo, memorizado por proceso.

    Se reutiliza entre invocaciones de la misma Lambda tibia: construirlo por llamada rehace
    la sesion HTTP y agrega latencia a cada mensaje.
    """
    global _client
    if _client is None:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise LLMError(
                "Falta GEMINI_API_KEY (en AWS se lee de Secrets Manager, no del entorno en claro)",
                provider="gemini",
                is_fatal=True,
            )
        _client = GeminiClient(api_key)
    return _client


def reset_client() -> None:
    """Limpia el cliente memorizado. Para tests y para rotacion de credenciales."""
    global _client
    _client = None


def model_for(tier: ModelTier) -> ModelSpec:
    """Modelo y precio vigentes de un tier, sin construir cliente (logs y estimaciones)."""
    return _MODELS[tier]
