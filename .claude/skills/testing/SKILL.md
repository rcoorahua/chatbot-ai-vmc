---
name: testing
description: Disciplina de testing de Subastín — corre la suite completa, decide si el cambio exige ampliar tests (default sí) y aplica la barra de calidad del repo. Usar después de CADA implementación o modificación de código backend, antes de dar algo por terminado, y cuando el usuario mencione tests, pytest, cobertura, QA, regresión o calidad de tests.
---

# Testing

## Regla dura

Ninguna implementación se da por terminada sin:
1. **Suite completa en verde** (no solo los tests del módulo tocado).
2. **Evaluación explícita** de si lo nuevo requiere tests — default SÍ; si se decide que no,
   justificarlo en una línea.
3. **Reporte honesto**: si algo falla, mostrar el output y arreglar ANTES de continuar; nunca
   reportar "listo" con tests rojos o saltados.

## Quick start

```bash
docker compose up -d          # dynamodb-local (:8001) + localstack sqs/s3 (:4566)
python -m pytest -q           # tests/ (config en pyproject.toml)
```

- Integración contra **dynamodb-local/localstack reales** (claves y GSIs de verdad; prohibido
  mockear boto3 en tests de repositories).
- Clientes de IA (`anthropic`, `google-genai`), HERALD y Slack **siempre mockeados** con fixture
  `autouse` — ningún test llama APIs de pago o externas.

## Qué testear al implementar (en orden de prioridad)

1. **El criterio de aceptación** del RF implementado (viene de la skill `spec-driven`). Los
   AC-001..009 de REQUERIMENTS.md §8 son la suite e2e objetivo: cada fase convierte los suyos
   en tests ejecutables.
2. **Invariantes y caminos de error**: idempotencia (RNF-004: mismo `client_message_id` ⇒ un
   solo mensaje), toma atómica (AC-005: la segunda toma falla limpio), transiciones de estado
   inválidas, RF-018 (sin evidencia ⇒ handoff, nunca inventar).
3. **Repositories** contra dynamodb-local, cubriendo cada GSI que usan.

## Barra de calidad (al escribir Y al revisar tests existentes)

- Un test = un comportamiento, con nombre que lo describe
  (`test_retry_mismo_client_message_id_no_duplica`).
- Asserts sobre comportamiento observable; prohibido `assert True`, asserts solo de status code,
  o acoplarse a detalles internos que un refactor rompería sin cambiar comportamiento.
- Sin dependencias de orden; cada test crea sus propios datos (ids únicos).
- Mocks de IA con respuestas realistas y tipadas (intent válido, texto no vacío), nunca vacíos.
- Si tocas un módulo cuyos tests son débiles para lo que cambias, fortalécelos en el mismo
  cambio — la deuda de tests no se acumula.
