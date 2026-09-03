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

import logging
import os
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from backend.core.config import get_settings

logger = logging.getLogger(__name__)


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
# llm-cost-optimizer). Precios de ai.google.dev/gemini-api/docs/pricing al 2026-09-01, tarifa
# estandar de pago; ya no hay precio promocional con vencimiento.
#
# Eleccion (2026-09-01, reemplaza a la de 2026-08-27): SOLO modelos con precio publicado en la
# pagina oficial. `gemini-3.7-flash` existe en la API pero NO figura en la tabla de precios
# (preview sin tarifa) y con key gratuita rechazaba sostenido ("high demand"): en la practica
# todo caia al respaldo mientras el costo se estimaba con una tarifa que Google no publica.
#   FAST   = 3.5-flash-lite (0.30/2.50): el lite GA mas nuevo; +0.05/M de input sobre
#            3.1-flash-lite a cambio de mejor routing — y el routing es la primera defensa
#            contra preguntas fuera de dominio (el margen de RAG_MIN_SCORE es angosto).
#            Respaldo: 3.1-flash-lite, mas barato y de alta disponibilidad.
#   ANSWER = 3.6-flash (1.50/7.50): el Flash mas capaz con precio GA publicado; mas barato en
#            salida que 3.5-flash (9.00) siendo mas nuevo. Respaldo: 3.5-flash.
@dataclass(frozen=True, slots=True)
class ModelSpec:
    name: str
    input_usd_per_million: float
    output_usd_per_million: float
    # Nivel de razonamiento (Gemini 3.x): el MINIMO que acepte cada modelo, porque esos tokens
    # salen del mismo presupuesto que max_output_tokens y ninguna de nuestras tareas necesita
    # razonamiento extendido. OJO: el piso varia POR MODELO y hay que PROBARLO al cambiar de
    # modelo — 3.7-flash rechazaba "minimal" con APIError (tumbo al redactor el 2026-09-01),
    # pero 3.5-flash-lite, 3.5-flash y 3.6-flash lo aceptan (sondeados el 2026-09-01; con
    # "low", 3.6-flash gasto 12 tokens pensando y devolvio vacio en un tope chico).
    thinking_level: str = "minimal"
    # Modelo de RESPALDO para cuando el principal rechaza la llamada (visto 2026-09-01:
    # "high demand" sostenido con key gratuita mientras otros modelos respondian normal).
    # Un solo reintento, con log de ambos errores si tambien falla. Lleva su PROPIO precio:
    # el costo en AIUsage se calcula con la tarifa del modelo que realmente respondio.
    fallback: ModelSpec | None = None


_MODELS: dict[ModelTier, ModelSpec] = {
    ModelTier.FAST: ModelSpec(
        name="gemini-3.5-flash-lite",
        input_usd_per_million=0.30,
        output_usd_per_million=2.50,
        fallback=ModelSpec(
            name="gemini-3.1-flash-lite",
            input_usd_per_million=0.25,
            output_usd_per_million=1.50,
        ),
    ),
    ModelTier.ANSWER: ModelSpec(
        name="gemini-3.6-flash",
        input_usd_per_million=1.50,
        output_usd_per_million=7.50,
        fallback=ModelSpec(
            name="gemini-3.5-flash",
            input_usd_per_million=1.50,
            output_usd_per_million=9.00,
        ),
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

        Se resuelve por `model`, no por el tier: si la atendio el respaldo, se cobra con la
        tarifa del respaldo — antes se usaba siempre la del principal y el costo del respaldo
        quedaba subestimado en AIUsage.

        Los tokens cacheados se cobran distinto segun el proveedor; mientras no se active el
        caching (pendiente de D-004, que define el resumen de conversacion) se cuentan como
        input normal, que sobreestima antes que subestimar.
        """
        spec = spec_for_model(self.model, self.tier)
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


# Tope por llamada HTTP a Gemini, en milisegundos. Holgado para una redaccion con 600 tokens de
# salida (las medidas en local van de 1 a 7 s) y bastante menor que el timeout de la Lambda del
# worker, para que una llamada colgada no se lleve el job entero. Constante y no Settings a
# proposito: no es una politica de negocio y `core/config.py` lo esta tocando otra rama.
_HTTP_TIMEOUT_MS = 30_000


class GeminiClient(LLMClient):
    """Implementacion sobre el SDK `google-genai`."""

    provider = "gemini"

    def __init__(self, api_key: str) -> None:
        from google import genai
        from google.genai import types

        # Timeout EXPLICITO por llamada. El SDK trae `None` por defecto y una conexion que se
        # queda muda cuelga al worker entero: paso el 2026-09-03 en local (13 minutos sin
        # respuesta ni error, con todos los jobs siguientes esperando detras) y en Lambda
        # agotaria el timeout de la funcion sin dejar rastro del motivo (DETAILS.md §4.18).
        # Con timeout, la llamada muerta se convierte en un LLMError de conexion: cae al
        # respaldo y, si tambien falla, el redactor responde con el texto fijo.
        self._client = genai.Client(
            api_key=api_key, http_options=types.HttpOptions(timeout=_HTTP_TIMEOUT_MS)
        )

    def generate(
        self,
        *,
        tier: ModelTier,
        system: str,
        messages: list[dict[str, str]],
        max_output_tokens: int,
        temperature: float | None = None,
    ) -> LLMResponse:
        from google.genai import types

        spec = _MODELS[tier]
        config: dict[str, Any] = {"max_output_tokens": max_output_tokens}
        if system:
            config["system_instruction"] = system
        if temperature is not None:
            config["temperature"] = temperature

        # Los Gemini 3.x razonan por defecto y esos tokens salen del MISMO presupuesto que
        # max_output_tokens: sin bajarlo, una clasificacion con tope de 24 tokens se gasta el
        # presupuesto pensando y devuelve vacio. El nivel vive en el ModelSpec porque el piso
        # aceptado varia por modelo (ver el comentario en la clase).
        config["thinking_config"] = types.ThinkingConfig(thinking_level=spec.thinking_level)
        # No usamos tools/function calling, pero el SDK lo trae ENCENDIDO por defecto y ademas
        # loguea un warning por cada llamada ("Direct use of automatic function calling...").
        # Se apaga la funcion, no el logger: silenciar el logger taparia warnings reales.
        config["automatic_function_calling"] = types.AutomaticFunctionCallingConfig(disable=True)

        contents = self._to_contents(types, messages)
        started = time.perf_counter()
        model_name = spec.name
        try:
            response = self._client.models.generate_content(
                model=model_name,
                contents=contents,
                config=types.GenerateContentConfig(**config),
            )
        except Exception as exc:  # noqa: BLE001 — APIError y tambien timeouts/red del transporte
            if not spec.fallback:
                raise self._normalize(exc) from exc
            # Reintento UNICO con el respaldo. Aplica a cualquier fallo del principal: si es
            # un error que el respaldo comparte (key invalida), fallara igual y ambos quedan
            # en el log; si es capacidad del modelo o una conexion colgada (los dos casos
            # vistos), el respaldo salva la respuesta en vez de degradar al texto fijo.
            logger.warning(
                "llm.fallback", extra={"model": model_name, "error": str(self._normalize(exc))}
            )
            model_name = spec.fallback.name
            # El respaldo lleva su propia config: el piso de thinking varia por modelo.
            config["thinking_config"] = types.ThinkingConfig(
                thinking_level=spec.fallback.thinking_level
            )
            try:
                response = self._client.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config=types.GenerateContentConfig(**config),
                )
            except Exception as exc2:  # noqa: BLE001 — mismo criterio que el principal
                raise self._normalize(exc2) from exc2
        latency_ms = int((time.perf_counter() - started) * 1000)

        return LLMResponse(
            text=self._extract_text(response),
            # El modelo que REALMENTE respondio: si salvo el respaldo, AIUsage debe decirlo.
            model=model_name,
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
        message = str(getattr(exc, "message", "") or exc) or type(exc).__name__
        if code is None:
            # No vino del API (timeout, conexion cortada, DNS): es un fallo de transporte y se
            # reintenta como tal. Se deja el tipo en el mensaje para verlo en el log.
            return LLMError(
                f"{type(exc).__name__}: {message}", provider=self.provider, is_connection=True
            )
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
        # Settings lee `.env` (dev) o las variables que inyecta el entorno (AWS). Antes se leia
        # solo `os.environ`, y pydantic NO exporta `.env` al proceso: la key en `.env` nunca
        # llegaba aqui y el bot caia al fallback en silencio. `os.environ` queda como respaldo
        # para quien exporta la variable a mano.
        api_key = get_settings().gemini_api_key or os.environ.get("GEMINI_API_KEY")
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


def spec_for_model(model: str | None, tier: ModelTier) -> ModelSpec:
    """Spec (y precio) del modelo que REALMENTE atendio una llamada del tier.

    Si `model` es el respaldo del tier, devuelve el spec del respaldo con su propia tarifa;
    en cualquier otro caso (el principal, None, o un doble de tests) devuelve el principal.
    """
    spec = _MODELS[tier]
    if model and spec.fallback and model == spec.fallback.name:
        return spec.fallback
    return spec


def cost_for(model: str | None, usage: dict[str, int] | None, *, tier: ModelTier) -> float:
    """Costo de una llamada con el precio del modelo que la atendio (ver `spec_for_model`).

    Los tokens cacheados se cobran como input mientras el caching no este activo:
    sobreestimar antes que subestimar (misma regla que `LLMResponse.estimated_cost_usd`).
    """
    if not usage:
        return 0.0
    spec = spec_for_model(model, tier)
    billable_input = usage.get("input", 0) + usage.get("cached_read", 0)
    return (
        billable_input * spec.input_usd_per_million
        + usage.get("output", 0) * spec.output_usd_per_million
    ) / 1_000_000
