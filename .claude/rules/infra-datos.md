---
paths:
  - "infra/**"
  - "scripts/local_setup.py"
  - "scripts/reset_local.py"
  - "backend/**/repository.py"
  - "backend/conversations/**"
  - "backend/core/config.py"
  - ".env.example"
  - "tests/test_local_setup.py"
  - "tests/test_dynamo_queries.py"
---

# Esquema DynamoDB, colas y variables de entorno

- El esquema DynamoDB **y el TTL** están **duplicados a propósito** en `infra/stacks/subastin_stack.py`
  (AWS) y `scripts/local_setup.py` (local, `TABLAS_CON_TTL`). Cambiar una clave, un GSI o el TTL
  exige tocar **los dos** — si no, las pruebas pasan en local contra un esquema que no existe en
  stage (hasta 2026-09-07 el TTL solo existía en AWS y el camino de caducidad nunca corría en dev).
  **Lo mismo con las colas (2026-09-08)**: el *visibility timeout* (regla "≥ 6× el timeout del
  worker") vive en `infra/config.py` (`VISIBILITY_FACTOR`, `WORKER_NOTIFY_TIMEOUT_S`) y su
  espejo en `local_setup.VISIBILITY_TIMEOUT_S`, comparados por `tests/test_local_setup.py`.
  Antes la cola local usaba el default de SQS (30 s) y un job de IA de más de 30 s se
  reentregaba a medio procesar: el bot respondió DOS veces la misma pregunta. `create_queue`
  no cambia atributos de una cola existente, por eso `local_setup` llama `set_queue_attributes`.
- Los nombres de variable de entorno son el contrato entre los tres entornos: `common_env` del
  stack, `nombres_de_tabla()` de `local_setup.py` y `.env.example` usan **los mismos**
  (`TABLE_*`, `IMAGES_BUCKET`, `AI_JOBS_QUEUE_URL`, `*_ENDPOINT_URL`).
- La conversación del usuario autenticado tiene **id determinista** (`uuid5` del `user_id` en
  `conversations/service.py`): es lo que hace atómico "máximo 1" (D-002) entre dos pestañas.
  Cambiar el namespace "pierde" las conversaciones existentes.
- Los marcadores de idempotencia viven en la tabla Messages con SK `CMID#…`; todo listado acota
  la SK por arriba con `"3"` para no verlos. Un query nuevo sin esa cota los devuelve como mensajes
  (y en orden descendente, primero).
