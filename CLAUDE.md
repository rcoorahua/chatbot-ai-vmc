# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# Subastín (chatbot-ai-vmc)

Plataforma de atención propia de VMC que reemplaza a Intercom: chat web con IA
(Gemini clasifica y redacta —TD-008—, RAG en Pinecone, catálogo HERALD) y handoff a asesores humanos.
Arquitectura AWS serverless (API Gateway HTTP API + Lambda + SQS + DynamoDB) con CDK v2 Python.
**Fuente de verdad funcional: [REQUERIMENTS.md](REQUERIMENTS.md)** (RF/RNF/RB/AC/D + modelo
DynamoDB v1.0). **Fuente de verdad de arquitectura: [PLAN.md](PLAN.md).** El desglose en tickets tomables y sus
dependencias está en [BACKLOG.md](BACKLOG.md) — consultarlo al planear o repartir trabajo.

## Comandos

Entorno: `.venv` + `pip install -e ".[dev]"`. Python ≥ 3.12, Node 22 (frontend y `node --check`
del widget). `.env` a partir de `.env.example`: el chat necesita `VMC_IDENTITY_SECRET` y
`SESSION_SIGNING_KEY` (cualquier texto en dev).

```powershell
docker compose up -d              # dynamodb-local (:8001) + localstack sqs/s3 (:4566)
python -m scripts.local_setup     # crea las 5 tablas, 2 colas y el bucket — idempotente
python -m scripts.seed_data       # dataset base de las pruebas de lectura
uvicorn backend.api.main:app --reload --port 8000   # http://localhost:8000/docs
cd widget; python -m http.server 8080                # widget: http://localhost:8080/test.html

python -m scripts.helpcenter_fetch                   # Centro de Ayuda -> data/helpcenter/*.md + chunks.json
python -m scripts.helpcenter_upload --verify         # sube a Pinecone e imprime scores (calibra RAG_MIN_SCORE)
python -m scripts.advisor_token --sub sub-ana-001 --name "Ana Torres"   # Bearer para /advisor en local (ADVISOR_DEV_AUTH=1)
python -m scripts.run_ai_worker                      # el bot responde en local (worker contra la cola de localstack; pide GEMINI_API_KEY)

python -m pytest -q                                  # suite completa (lo que corre el CI)
python -m pytest tests/test_dynamo_queries.py -q     # un archivo
python -m pytest -k "gsi1" -q                        # un patrón / una prueba
python -m ruff check .            # lint (line-length 100, reglas E/F/I/UP/B)

cd infra; npx -y aws-cdk@2 synth -c stage=stage      # valida la infra sin desplegar
cd frontend; npm run dev                             # Next.js 16 en :3000
```

`local_setup` y `seed_data` hay que **re-ejecutarlos tras cada reinicio de contenedores**:
dynamodb-local corre `-inMemory` y pierde las tablas.

Los tests corren contra **dynamodb-local real**, no mocks: si los contenedores no están arriba
se saltan en local, pero **fallan duro en CI** (`conftest.py` distingue por la variable `CI`).
De ahí que un GSI mal definido se detecte en `tests/test_dynamo_queries.py` y no en producción.

Hook local obligatorio al clonar: `git config core.hooksPath .githooks` (bloquea push directo a
`main`/`develop`; escape hatch `ALLOW_DIRECT_PUSH=1`).

## Metodología (skills en `.claude/skills/`)

**Núcleo del flujo (siempre activas):**
- **spec-driven**: antes de implementar — mapear a RF/AC de REQUERIMENTS.md, revisar D/TD
  abiertas, criterio de aceptación primero, autonomía acotada (cuándo parar y escalar).
- **testing**: después de cada implementación — suite COMPLETA en verde + evaluar ampliar tests
  a lo nuevo (default sí).
- **commit**: protocolo "implementa X" = pull develop → rama `feature/`/`fix/` → spec-driven →
  implementar → tests en verde → push → PR a `develop` (nunca push directo). `develop` = trunk
  (deploy → stage), `main` = producción protegida (PR de release, deploy → prod). Conventional
  Commits con trazabilidad `Implementa RF-xxx` / `Cierra D-xxx`.
- **deploy**: CDK stage/prod con precondiciones; prod solo con confirmación explícita.

**Especializadas (cargar según el tema):** `llm-cost-optimizer` (toda llamada IA: AIUsage,
max_tokens, caching, ruteo) · `rag-architect` (F3: Pinecone, chunking, evaluación) ·
`prompt-governance` (cambios a `agent/prompts.py`: golden set + eval) · `ci-cd` (workflows de
GitHub Actions) · `docker-dev` (compose/Dockerfiles) · `security-guidance` (código sensible +
reglas RNF-005/RF-052) · `skill-auditor` (auditar skills de terceros ANTES de instalar) ·
`write-a-skill` (crear/modificar skills de este repo).

**Hook activo:** `.claude/hooks/security_reminder_hook.py` (PreToolUse en Edit/Write, wiring en
`.claude/settings.json`) bloquea anti-patrones de seguridad al escribir código.

## ⛔ REGLA PRINCIPAL — leer antes de implementar cualquier cosa

Antes de implementar una funcionalidad, revisar las listas de decisiones abiertas de abajo.
**Si lo que se va a implementar depende de una decisión abierta (D-xxx o TD-xxx): DETENERSE y
avisar al usuario** ("aguanta — esto depende de D-xxx que sigue abierta") en vez de asumir un valor.
Ningún pendiente se convierte en supuesto técnico oculto. Cuando el usuario cierre una decisión,
moverla a "cerradas" aquí y reflejarla en PLAN.md.

## Decisiones técnicas cerradas (no re-discutir)

- **T1** HTTP API (API Gateway v2), no REST API. JWT authorizer nativo de Cognito para `/advisor` y `/dashboard`.
- **T2** Backend FastAPI completo en UNA Lambda con Mangum (`lifespan="off"`), ruta `$default`.
- **T3** Workers SQS en Lambdas separadas (`worker-ai`, `worker-notify`); la API solo encola y responde 202. Workers devuelven `batchItemFailures`.
- **T4** Infra con CDK v2 en Python (`infra/`), un stack por stage vía `-c stage=stage|prod`.
- **T5** dev = local con Docker (dynamodb-local + localstack sqs/s3, sin cuenta AWS); stage/prod = CDK.
- **T6** FastAPI se mantiene como framework (compatible con Lambda vía Mangum).
- **T7** Datos/estados/código en inglés (`PENDING_ADVISOR`…); UI en español; docs en español.
- **T8** Respuesta IA asíncrona: POST → 202 + SQS; el frontend hace polling.
- **T9** ~~Haiku para clasificación; Gemini para redacción.~~ **Superada provisionalmente por
  TD-008** (2026-08-27): Gemini (SDK `google-genai`) atiende ambas etapas. Haiku
  (`claude-haiku-4-5`) sigue siendo el plan B para clasificar si el golden set lo justifica.
- Modelo de datos: 5 tablas DynamoDB (`Conversations`, `Messages`, `Tickets`, `Advisors`, `AIUsage`) — claves/GSIs en PLAN.md §4, con los ajustes 1–5 de la revisión (unread_count, wait_message_sent, TTL en Messages, idempotencia transaccional, GSI sparse opcional).
- `visibility_timeout` de cada cola ≥ 6× el timeout de su worker.
- Los GSI se deciden ANTES de crear tablas en stage (backfill posterior es migración manual).

## Decisiones de NEGOCIO cerradas (2026-08-27, Aaron)

Reflejadas en PLAN.md §2/§4/§9 y REQUERIMENTS.md §6. Código: `core/auth.py`,
`conversations/service.py`, `widget/`.

- **D-001 Identidad VMC ↔ Subastín**: JWT de identidad **firmado por el servidor de VMC** (HS256,
  secreto compartido `VMC_IDENTITY_SECRET`), dejado en la página como
  `window.subastinSettings.userJwt` y verificado en `POST /chat/sessions`, que devuelve un token de
  sesión propio (`SESSION_SIGNING_KEY`). Es la "identity verification" de Intercom en su variante
  vigente (JWT; el `user_hash` está deprecado). **Ajuste técnico sobre lo pedido** ("el widget lee
  la cookie"): `subastop_jwt` y `subastop_auth_user` son **HttpOnly** —ningún script puede
  leerlas— y compartir el secreto de sesión de VMC dejaría a Subastín forjar sesiones de VMC.
  Contrato para VMC en `widget/README.md`. La identidad visible del asistente es **"Subastín"**.
- **D-002 Conversaciones activas**: **1** por usuario (autenticado y anónimo). Máximo **5 tickets
  activos** por usuario (se aplica en F5). **Anónimo = solo FAQ**: sin handoff ni ticket, porque no
  hay forma de identificarlo para continuar un ticket días después; el widget lo invita a iniciar
  sesión. Consecuencias: cierra **D-019** (no existe el ticket anónimo) y deja **RF-003 / AC-003 /
  RB-002 sin efecto** — el spec aún dice "correo obligatorio al derivar anónimo"; hay que retirarlos
  o confirmar la lectura alternativa (ticket anónimo que muere con la sesión).
- **D-003 Cierre e historial**: **una sola conversación permanente** por usuario autenticado; no se
  crea otra ni se "reabre". Lo que se cierra son los **tickets**, que quedan en el hilo como notas
  de sistema (mensaje SYSTEM `TICKET_CLOSED` → "Ticket cerrado"), igual que las notas de Intercom.
  Cierra también **D-017**: N tickets por conversación (máx. 5 activos) y cerrar un ticket **no**
  cierra la conversación. Sigue abierto el autocierre de un ticket sin respuesta (lo absorbe D-007).
- **D-018 (provisional, derivada de RF-004)**: sesión anónima = la pestaña del navegador
  (`sessionStorage`) con token de 24 h (`ANONYMOUS_SESSION_TTL_HOURS`). Confirmar con Silvana + Julio.
- **D-021 Alta de asesores**: auto-alta `ACTIVE` al primer login con JWT válido de Cognito
  (`advisors/service.py`). La invitación en Cognito es el único control; `DISABLED` se rechaza.
- **D-022 Quién responde**: solo el asesor que **tomó** la conversación (asignada a él,
  `IN_ATTENTION`); tomar no requiere ticket. Se puede tomar `PENDING_ADVISOR` y también
  `BOT_ATTENDING` sin asesor (intervención proactiva); tomarla apaga el bot. Toma atómica (AC-005).
- **D-023 Cierre mínimo sin ticket (provisional hasta F5)**: `POST /advisor/…/close` deja la nota
  `TICKET_CLOSED`, devuelve la conversación a `BOT_ATTENDING` con bot encendido y sin asesor. No
  crea fila en Tickets; cuando exista el módulo, el cierre pasa a cerrar el ticket.
- **D-004 Contexto para IA (2026-08-28)**: **no hay resumen**. La memoria del bot son los últimos
  **20 mensajes de la última hora** (`service.context_window`). Pasada la ventana, el mensaje se
  atiende solo. `summary`/`summary_updated_at` quedan en el modelo sin uso.
- **D-005 Guardrails (2026-08-28)**: 2000 caracteres por mensaje; **10 mensajes/min** por
  conversación → 429 con `Retry-After` (el rechazado no se persiste); imágenes 5 MB, 3 por
  mensaje, 20 por hora, JPG/PNG/WebP. **Sin tope acumulativo**: con D-003 la conversación es
  permanente, así que un tope duro la dejaría inservible de por vida.
- **D-006 Triviales (2026-08-28)**: saludo/gracias sueltos y mensaje repetido (<10 min) reciben
  respuesta fija sin llamada IA (`agent/trivial.py`); el aviso de repetición sale UNA vez y
  luego silencio. El spam por volumen lo frena el rate limit de D-005.
- **D-020 Debounce (2026-08-28)**: 6 s (`AI_DEBOUNCE_SECONDS`) como `DelaySeconds` de SQS; el
  worker salta el job si hay un mensaje más nuevo y el job del último responde la ráfaga en UNA
  llamada IA. Sin estado extra.

## Decisiones de NEGOCIO abiertas (D-xxx) — responsables: Silvana + Julio

Detalle en [REQUERIMENTS.md](REQUERIMENTS.md) §6 y PLAN.md §9.

| ID | Tema | Prio | Bloquea |
|---|---|---|---|
| D-007 | Duración IA OFF durante handoff | Alta | Implementada la opción recomendada como **provisional** (apagada hasta cierre del asesor); solo falta el temporizador si deciden expiración |
| D-008 | Taxonomía de problemas/tickets y campos | Alta | F5, tabla Tickets (`problem_type`, `category`, `tags`) |
| D-009 | Tags de negocio | Media | Tickets |
| D-010 | Campos de usuario VMC visibles/usables | Alta | F5, vista asesor |
| D-011 | Contrato HERALD (endpoints, auth, filtros) | Alta | F4 |
| D-012 | Fallback cuando HERALD caído | Media | F4 |
| D-013 | Métricas exactas del dashboard | Media | F7 |
| D-014 | Retención (¿6 meses?) conversaciones/imágenes | Alta | TTL, S3 lifecycle |
| D-015 | Procesamiento de imágenes para IA (modelo, resize) | Media | F6 |
| D-016 | Canal Slack y formato de notificación | Baja | worker-notify |

D-001…D-006, D-017, D-019, D-020 y D-021…D-023 **cerradas** (arriba); D-018 provisional.

## Decisiones TÉCNICAS abiertas (TD-xxx)

| ID | Tema | Recomendación actual |
|---|---|---|
| TD-001 | Entrega en tiempo real: polling vs API Gateway WebSocket | Polling **implementado** en `widget/subastin.js` (2,5 s abierto / 15 s cerrado, pausa con pestaña oculta); cumple RNF-001. WebSocket solo si el costo de sondeo lo justifica |
| TD-002 | Haiku vía API Anthropic directa vs Amazon Bedrock | Preguntar al equipo AWS si Bedrock está habilitado (PLAN §6.8); sin respuesta aún |
| TD-003 | Hosting frontend: Vercel vs Amplify | Sin recomendación aún; fuera del stack CDK en ambos casos |
| TD-004 | Cuentas AWS separadas stage/prod vs una sola | Separadas si el equipo AWS lo permite |
| TD-005 | `PythonFunction` (bundling) vs `DockerImageFunction` | PythonFunction mientras deps < 250 MB descomprimido |
| TD-007 | Dominio custom para la API + DNS/ACM | No bloquea MVP; URL default de API Gateway mientras tanto |
| TD-008 | ¿Gemini también clasifica, o vuelve Haiku (T9)? | **Gemini provisional** desde 2026-08-27: `gemini-3.1-flash-lite` clasifica ($0.25/$1.50 por 1M, 4× más barato que Haiku) y `gemini-3.7-flash` redacta. Un solo proveedor = una credencial y una integración menos. Se decide con el golden set de intents: si el routing no alcanza, el tier `FAST` de `core/llm.py` vuelve a Haiku (y ahí sí aplica TD-002). Ojo: el precio de `3.7-flash` es promocional hasta 2026-12-31 y se duplica el 2027-01-01 |

TD-006 **cerrada** (2026-08-24): la v0 (WhatsApp+Gemini) se eliminó del repo; backup en
`../chatbot-ai-vmc-v0-backup.zip`.

## Convenciones y layout

- Backend en `backend/` = **monolito modular** con dependencias en UNA dirección (regla completa
  en `backend/__init__.py`): entradas (`api/`, `workers/`) → dominio (`conversations`, `tickets`,
  `advisors`) → integraciones hoja (`agent`, `catalog`, `notifications`, `images`) → `core`.
  El dominio NUNCA importa integraciones; la composición vive en la entrada (p. ej. el pipeline
  IA en `workers/ai_worker.py`). Cada `repository.py` es el único que conoce claves/GSIs.
- Infra en `infra/`, app del asesor/dashboard en `frontend/` (Next.js), **widget del chat en
  `widget/`** (JS plano sin build, se embebe en VMC; `test.html` para probarlo). Todo el código
  nuevo sigue este layout.
- Estado por fase: **F1 (chat + identidad + persistencia) implementada** —
  `core/{config,aws,auth,clock,jobs}.py`, `conversations/*`, `api/routers/chat.py`, `widget/`.
  **Mensajería del asesor implementada** (adelanto de F5, 2026-08-27): `advisors/*`,
  `api/routers/advisor.py`, `api/dev_auth.py`; falta el módulo `tickets` (D-007/D-008) y D-010.
  **Pipeline IA implementado (F2+F3, 2026-08-28)**: `workers/ai_worker.py` compone debounce
  (D-020) → triviales (D-006) → clasificador (reglas→Gemini, TD-008) → RAG/redacción → handoff
  mínimo, con registro en `AIUsage` (`agent/usage.py`); el bot responde (local:
  `scripts/run_ai_worker.py`). Falta calibrar `RAG_MIN_SCORE`, la notificación Slack (D-016) y
  el ticket al derivar (D-008). El resto son stubs con docstrings; se implementan fase por fase
  (PLAN.md §8) cuando el usuario lo pida, no por adelantado.
- Python ≥ 3.12. Imágenes nunca en DynamoDB (S3 + metadata). Datos VMC solo lectura (RF-051).
- Deps: `backend/requirements.txt` es lo que CDK bundlea en las Lambdas; `pyproject.toml` es el
  entorno local de dev — mantener ambos en sync al agregar una dependencia.

**Invariantes que cruzan archivos (romperlos no lo detecta el linter):**

- El esquema DynamoDB está **duplicado a propósito** en `infra/stacks/subastin_stack.py` (AWS) y
  `scripts/local_setup.py` (local). Cambiar una clave o un GSI exige tocar **los dos** — si no,
  las pruebas pasan en local contra un esquema que no existe en stage.
- Los nombres de variable de entorno son el contrato entre los tres entornos: `common_env` del
  stack, `nombres_de_tabla()` de `local_setup.py` y `.env.example` usan **los mismos**
  (`TABLE_*`, `IMAGES_BUCKET`, `AI_JOBS_QUEUE_URL`, `*_ENDPOINT_URL`).
- `backend/api/main.py`: `Mangum(app, lifespan="off")` — con lifespan activo la Lambda se cuelga
  en el startup. Los routers `advisor`/`dashboard` **no** validan JWT en código: lo hace el
  authorizer de Cognito en el API Gateway (T1); el backend solo lee los claims que Mangum deja en
  `request.scope["aws.event"]` (`core/auth.py`). En local `ADVISOR_DEV_AUTH=1` instala
  `api/dev_auth.py`, que verifica un JWT propio (`ADVISOR_DEV_JWT_SECRET`) y deja los claims en el
  mismo sitio; se ignora dentro de una Lambda. Por eso no hay que "pushear el infra" para probar
  `/advisor`: el stack ya trae el User Pool y el authorizer, y se despliega junto con el código.
- Los workers devuelven siempre `{"batchItemFailures": [...]}` (contrato de SQS partial batch
  response, T3) — lo verifica `tests/test_smoke.py`.
- Secretos (Anthropic/Gemini/Pinecone/Slack/HERALD/VMC) se leen de **Secrets Manager en runtime**,
  nunca como variables de entorno del stack. Hoy `core/config.py` y `core/llm.py` los leen del
  entorno (dev); al desplegar hay que resolverlos desde el secreto antes de construir `Settings`.
- Dos secretos de identidad y no uno: `VMC_IDENTITY_SECRET` (lo comparte VMC, firma el JWT de
  identidad) y `SESSION_SIGNING_KEY` (propio, firma el token de sesión). Unificarlos permitiría
  presentar un token de sesión como identidad de VMC — `tests/test_core_auth.py` lo cubre.
- La conversación del usuario autenticado tiene **id determinista** (`uuid5` del `user_id` en
  `conversations/service.py`): es lo que hace atómico "máximo 1" (D-002) entre dos pestañas.
  Cambiar el namespace "pierde" las conversaciones existentes.
- Los marcadores de idempotencia viven en la tabla Messages con SK `CMID#…`; todo listado acota
  la SK por arriba con `"3"` para no verlos. Un query nuevo sin esa cota los devuelve como mensajes
  (y en orden descendente, primero).
- **RAG**: el índice de Pinecone usa **embedding integrado** (`multilingual-e5-large` dentro de
  Pinecone). Ingesta y consulta embeben con el mismo modelo por construcción; crear el índice a
  mano con otro modelo no da error, solo resultados malos. Por eso lo crea
  `scripts/helpcenter_upload.py`, no la consola web. Gemini **no** interviene en los embeddings.
- `RAG_MIN_SCORE` es RF-018 hecho código: Pinecone siempre devuelve los `top_k` más cercanos,
  también para una pregunta ajena al Centro de Ayuda. **Está sin calibrar** — el valor real se
  mide con `python -m scripts.helpcenter_upload --verify`.
- Los ids de chunk son estables (`hc-<artículo>-<pregunta>-<huella>`): con ids posicionales, una
  pregunta nueva corre a todas las siguientes y el upsert sobrescribe cada vector con el texto de
  otro, sin fallar. El upsert es aditivo: para un refresco completo, `--replace`.
- `frontend/` usa **Next.js 16** (App Router, React 19, Tailwind v4): APIs y convenciones difieren
  del entrenamiento — consultar `frontend/node_modules/next/dist/docs/` antes de escribir código,
  como pide `frontend/AGENTS.md`. Se despliega fuera de CDK (TD-003).
