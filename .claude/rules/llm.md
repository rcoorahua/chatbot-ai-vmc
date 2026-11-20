---
paths:
  - "backend/core/llm.py"
  - "backend/agent/**"
  - "backend/workers/**"
---

# Modelos de Gemini (`core/llm.py`)

- **`core/llm.py` — quirks por modelo de Gemini 3.x, no generalizar entre tiers**: el piso de
  `thinking_level` que acepta cada modelo varía (`ModelSpec.thinking_level`) y hay que
  **probarlo con una llamada real al cambiar de modelo** — `3.7-flash` rechazaba `"minimal"`
  con `APIError` (tumbó al redactor en local el 2026-09-01, cayendo siempre al fallback fijo
  como si no hubiera evidencia), mientras que `3.5-flash-lite`, `3.5-flash` y `3.6-flash` lo
  aceptan (sondeados 2026-09-01; con `"low"`, `3.6-flash` gastó el tope pensando y devolvió
  vacío). Cada tier lleva un respaldo (`ModelSpec.fallback`) **con su propia tarifa**: el costo
  en AIUsage se calcula con el precio del modelo que REALMENTE respondió (`llm.cost_for`),
  nunca con el del principal. Al agregar un modelo o tier nuevo, no asumir que le sirve la
  config de otro — probarlo aparte. Modelos vigentes: ver TD-008. **(2026-09-03)** Timeout
  por tier (`_TIER_TIMEOUT_MS`: 15 s FAST, 40 s ANSWER; el SDK trae `None` y colgó el worker
  13 min) y todo fallo llega como `LLMError` con `kind` (`quota`/`rate_limit`/
  `client_timeout`/`provider`/`auth`) que AIUsage guarda en `error` con `status=ERROR`. Con
  evidencia y modelo caído el bot dice que **no está disponible** (`MODEL_UNAVAILABLE_*`),
  nunca "no tengo ese dato". **La key gratuita de Gemini tiene 20 peticiones por ventana en
  `3.6-flash`**: una batería la agota y toda prueba manual posterior cae en ese mensaje.
