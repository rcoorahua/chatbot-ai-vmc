---
name: llm-cost-optimizer
description: Ingeniería de costos LLM para Subastín — instrumentación en AIUsage, ruteo Haiku/Gemini, prompt caching, control de longitud de salida y presupuestos. Usar proactivamente al implementar o modificar cualquier llamada a IA (agent/), al hablar de costos, tokens, max_tokens, caching, "qué modelo usar" o consumo, y ANTES de lanzar cualquier feature nueva de IA — no esperar a que el costo sea un problema.
---

# LLM Cost Optimizer (adaptado a Subastín)

Los costos de IA son costos de ingeniería: **medir primero, optimizar después, monitorear
siempre**. En Subastín la arquitectura ya trae las dos piezas clave — ruteo (Haiku clasifica,
solo lo necesario llega a Gemini) y observabilidad (tabla `AIUsage`) — esta skill evita que se
degraden al implementar.

## Reglas duras al escribir código de IA (`backend/agent/`)

1. **Toda llamada a Haiku/Gemini registra en `AIUsage`** (tokens in/out, `cached_tokens`, costo
   estimado, latencia, intent, `rag_used`, `handoff_triggered`) — sin excepción. Si no se puede
   medir, no se lanza.
2. **`max_tokens` explícito por tipo de llamada**, nunca global ni ausente: clasificación
   (~pocas decenas), redacción (según D-005). Endpoint sin cap = fuga de costo activa.
3. **Ruteo antes que modelo grande**: nada llega a Gemini sin pasar por el clasificador Haiku
   (RF-015) o por las reglas determinísticas de D-006 (saludos/spam sin llamada IA — ahorro
   directo). El debounce (D-020) agrupa mensajes para no pagar N llamadas por frases partidas.
4. **Prompt caching**: system prompts estables primero, contenido volátil al final;
   `cache_control` en el prefijo estable. Verificar con `cached_tokens` en AIUsage — si es 0
   sostenido, hay un invalidador (timestamp/uuid en el prompt) que hay que cazar.
5. **Salida controlada**: instrucción de longitud + salida estructurada donde aplique; los
   LLMs sobre-generan por defecto.
6. **Imágenes**: jamás enviar originales a IA (RNF-008); resize/compresión según D-015.

## Señales proactivas (flaggear sin que pregunten)

| Señal | Acción |
|---|---|
| Llamada IA sin registro en AIUsage | Bloquear: instrumentar es el entregable #1 |
| `max_tokens` ausente en una llamada | Flag inmediato: fuga de costo |
| System prompt grande enviado en cada request sin caching | Objetivo de caching de alto valor |
| Mensajes triviales llegando al pipeline completo | Aplicar/recordar D-006 |
| Todo el tráfico yendo a Gemini | El monocultivo de modelo es el patrón #1 de sobre-gasto |

## Presupuestos y degradación (diseñar con D-005)

Límites por conversación/usuario/día con alerta blanda al 80%; al excederse: respuesta
determinística → handoff, nunca "seguir pagando". El dashboard de costos queda FUERA del MVP
(RF-049) pero los datos se capturan desde F2 — no se pueden reconstruir después.

## Precios y modelos

Nunca hardcodear precios como hechos: `estimated_cost_usd` se calcula con el precio vigente al
momento de la ejecución (constante configurable con fecha, en `core/config.py`). Modelos
actuales: Haiku `claude-haiku-4-5` (T9); acceso directo vs Bedrock → TD-002.

## Fuera de esta skill

Diseño del pipeline RAG → skill `rag-architect`. Calidad/gobierno de prompts → skill
`prompt-governance`.
