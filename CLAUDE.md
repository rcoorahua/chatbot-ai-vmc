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
`SESSION_SIGNING_KEY` (cualquier texto en dev) y, para que el bot responda,
`AI_JOBS_QUEUE_URL=http://localhost:4566/000000000000/subastin-dev-ai-jobs` — sin ella el
mensaje se guarda como `QUEUE_FAILED` y nunca llega al worker. Una variable vacía en `.env` cae
al default del campo (`core/config.py`), así que copiar la plantilla tal cual no rompe nada.
Para que el bot responda de verdad: `GEMINI_API_KEY` (y `PINECONE_API_KEY`, sin ella toda FAQ
deriva). Observabilidad: `LOG_LEVEL`/`LOG_CONTENT`/`LOG_FORMAT`/`DEV_OBSERVABILITY` vacías =
decidir por `STAGE` (dev y stage detallados, prod sobrio; ver `core/observability.py`).

```powershell
docker compose up -d              # dynamodb-local (:8001) + localstack sqs/s3 (:4566)
python -m scripts.local_setup     # crea las 5 tablas, 2 colas y el bucket — idempotente
python -m scripts.seed_data       # dataset base de las pruebas de lectura
python -m scripts.reset_local     # borra+recrea tablas, purga colas y reseedea — SIN tocar Docker
uvicorn backend.api.main:app --reload --port 8000   # http://localhost:8000/docs
cd widget; python -m http.server 8080                # widget: http://localhost:8080/test.html

python -m scripts.helpcenter_fetch                   # Centro de Ayuda -> data/helpcenter/*.md + chunks.json
python -m scripts.helpcenter_upload --verify "cuanto es la comision"   # sube a Pinecone e imprime scores (calibra RAG_MIN_SCORE); --replace = refresco completo
python -m scripts.advisor_token --sub sub-ana-001 --name "Ana Torres"   # Bearer para /advisor en local (ADVISOR_DEV_AUTH=1)
python -m scripts.run_ai_worker                      # el bot responde en local (worker contra la cola de localstack; pide GEMINI_API_KEY)
python -m scripts.eval_intents                       # eval REAL del golden set contra Gemini (~1 centavo); obligatoria al tocar agent/prompts.py o heuristics.py

python -m pytest -q                                  # suite completa (lo que corre el CI)
python -m pytest tests/test_dynamo_queries.py -q     # un archivo
python -m pytest -k "gsi1" -q                        # un patrón / una prueba
python -m ruff check .            # lint (line-length 100, reglas E/F/I/UP/B)
node --check widget/subastin.js   # sintaxis del widget (no tiene tests)

cd infra; npx -y aws-cdk@2 synth -c stage=stage      # valida la infra sin desplegar (lo corre el CI)
cd infra; npx -y aws-cdk@2 watch -c stage=stage      # hotswap del código Lambda (~3 s); cambios de infra = deploy
cd frontend; npm run dev                             # Next.js 16 en :3000
cd frontend; npm run lint; npm run build             # eslint + build de producción
```

`local_setup` y `seed_data` hay que **re-ejecutarlos tras cada reinicio de contenedores**:
dynamodb-local corre `-inMemory` y pierde las tablas. Para limpiar lo que ensuciaron pruebas
manuales sin reiniciar Docker (más rápido y no interrumpe nada), `python -m scripts.reset_local`
hace las dos cosas en un solo paso y de paso purga las colas; el worker de IA (`run_ai_worker`)
no necesita reiniciarse porque no guarda estado entre jobs.

Los tests corren contra **dynamodb-local real**, no mocks: si los contenedores no están arriba
se saltan en local, pero **fallan duro en CI** (`conftest.py` distingue por la variable `CI`).
De ahí que un GSI mal definido se detecte en `tests/test_dynamo_queries.py` y no en producción.

Convenciones de la suite (`tests/conftest.py`): `conftest` fija SIEMPRE los endpoints locales y
apunta `AWS_CONFIG_FILE` a `devnull` — un `.env` en blanco no puede convertir la suite en una
escritura a AWS real; también fija secretos de identidad de prueba, así que no necesita `.env`.
Los tests que **escriben** crean ids con el fixture `conversacion_temporal` (`conv_test_*`, se
borran al terminar y se purgan al arrancar) y **nunca mutan el dataset de `seed_data`**, que es
lo que consultan las pruebas de lectura. Los tests de IA sustituyen `LLMClient` por un doble
(`tests/test_agent_llm.py`), no simulan el SDK: la suite corre sin claves ni red.

CI (`.github/workflows/ci.yml`): lint + tests (dynamodb-local 2.5.2 y localstack 3.7 como
`services`, mismos tags que `docker-compose.yml`) + `cdk synth`, sin credenciales AWS. El CD
(`deploy.yml`) está **maquetado y apagado** (`if: false`) hasta tener cuenta AWS (PLAN.md §6);
`infra/config.py` lleva `account=None` a propósito.

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
  cierra la conversación. El autocierre de un ticket sin respuesta quedó descartado por D-007
  (cerrada 28/08: nada se cierra ni se re-enciende solo).
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
- **D-005 Guardrails (2026-08-28, largo de mensaje revisado 2026-08-31)**: **500 caracteres**
  por mensaje (bajado de 2000: de sobra para el tono conversacional del chat, sin invitar a
  pegar párrafos); **10 mensajes/min** por conversación → 429 con `Retry-After` (el rechazado
  no se persiste); imágenes 5 MB, 3 por mensaje, 20 por hora, JPG/PNG/WebP. **Sin tope
  acumulativo**: con D-003 la conversación es permanente, así que un tope duro la dejaría
  inservible de por vida.
- **D-007 IA OFF en handoff (2026-08-28)**: opción simple — la IA **no se re-enciende sola**.
  Queda apagada hasta que un asesor tome y cierre el caso (D-023 la devuelve al bot). Sin
  expiración ni temporizador; si nadie atiende, el caso espera en la bandeja.
- **D-006 Triviales (2026-08-28)**: saludo/gracias sueltos y mensaje repetido (<10 min) reciben
  respuesta fija sin llamada IA (`agent/trivial.py`); el aviso de repetición sale UNA vez y
  luego silencio. El spam por volumen lo frena el rate limit de D-005.
- **D-020 Debounce (2026-08-28)**: 6 s (`AI_DEBOUNCE_SECONDS`) como `DelaySeconds` de SQS; el
  worker salta el job si hay un mensaje más nuevo y el job del último responde la ráfaga en UNA
  llamada IA. Sin estado extra.
- **D-024 Guardrails de seguridad (2026-08-28)**: intento de manipulación (jailbreak, pedir el
  prompt, cambiar el rol, autoridad falsa, etiquetas del prompt) → respuesta fija amable, **sin
  IA y sin derivar**; datos de OTROS usuarios (RF-052) → fija de privacidad, sin derivar. Capa
  de salida: cifra o enlace que no esté en la evidencia, o fuga del prompt → se descarta la
  respuesta y deriva como "sin evidencia". Todo en `agent/guardrails.py`; corre después de la
  repetición (D-006) a propósito, para que insistir no gane una fija por intento.
- **D-025 Tono (2026-08-28)**: español peruano cercano, natural; máximo **un emoji** por
  mensaje (fijos y generados), nunca junto a cifras o enlaces; sin markdown ni guiones largos
  como separador (`guardrails.tidy` limpia lo que se escape). Mensajes fijos en `agent/prompts.py`.
- **D-026 Eval de prompts (2026-08-28)**: golden set en `tests/golden/intents.jsonl`; en CI solo
  la parte determinista (`tests/test_golden_intents.py`). La eval real contra Gemini es manual:
  `python -m scripts.eval_intents` (~1 centavo) y exige ≥ 95% para mergear un cambio de prompt.
- **D-027 Tope diario de IA (2026-08-31) — ⚠️ DECIDIDA PERO NO IMPLEMENTADA**: **anónimo 10
  ejecuciones de IA al día**, contadas por `hash(IP)` **y** por sesión (se agota la primera de
  las dos); **autenticado 50/día** por `user_id` (no por IP: es preciso y no se comparte); **con
  asesor no consume cuota** (no hay llamada a modelo). `0 = ilimitado`, como
  `MAX_MESSAGES_PER_MINUTE`, y así queda en dev. Cuenta la **ejecución de IA**, no el mensaje:
  triviales y guardrails no gastan porque no cuestan (`agent/usage.py` ya lo distingue).
  Complementa a D-005, que es por minuto y por conversación: esto frena el costo acumulado de
  un mismo actor a lo largo del día. **Implementar apenas se pueda** (T-09 en BACKLOG.md): hoy
  el único freno ante un anónimo con un script es el de 10/min, que permite 14 400 llamadas
  diarias. Ojo con dos cosas al construirlo: la IP se guarda **hasheada** (es dato personal) y
  CGNAT móvil hace que muchos usuarios legítimos compartan IP.

## Decisiones de NEGOCIO abiertas (D-xxx) — responsables: Silvana + Julio

Detalle en [REQUERIMENTS.md](REQUERIMENTS.md) §6 y PLAN.md §9.

| ID | Tema | Prio | Bloquea |
|---|---|---|---|
| D-008 | Taxonomía de problemas/tickets y campos | Alta | F5, tabla Tickets (`problem_type`, `category`, `tags`) |
| D-009 | Tags de negocio | Media | Tickets |
| D-010 | Campos de usuario VMC visibles/usables | Alta | F5, vista asesor |
| D-011 | Contrato HERALD (endpoints, auth, filtros) | Alta | F4 |
| D-012 | Fallback cuando HERALD caído | Media | F4 |
| D-013 | Métricas exactas del dashboard | Media | F7 |
| D-014 | Retención (¿6 meses?) conversaciones/imágenes | Alta | TTL, S3 lifecycle |
| D-015 | Procesamiento de imágenes para IA (modelo, resize) | Media | F6 |
| D-016 | Canal Slack y formato de notificación | Baja | worker-notify |

D-001…D-007, D-017, D-019, D-020, D-021…D-023 y D-024…D-026 **cerradas** (arriba); D-018 provisional.
**D-027 cerrada pero SIN implementar** (tope diario de IA): es la única decisión cerrada con
código pendiente — ver T-09 en BACKLOG.md.

## Decisiones TÉCNICAS abiertas (TD-xxx)

| ID | Tema | Recomendación actual |
|---|---|---|
| TD-001 | Entrega en tiempo real: polling vs API Gateway WebSocket | **Sigue polling** (revisado 2026-09-01, Aaron): `widget/subastin.js` sondea 2,5 s abierto / 15 s cerrado, pausa con pestaña oculta. Webhook no es opción (el navegador no tiene URL pública) y SSE tampoco (HTTP API + Lambda no hace streaming, T1/T2), así que la alternativa real es una **API WebSocket aparte**. **No es un problema de latencia**: el piso lo pone el debounce de 6 s de D-020, y el polling solo agrega ~1,25 s de media sobre un presupuesto de 10 s (RNF-001). El argumento es **costo**: cada poll = 1 request de API Gateway + 1 Lambda + 1 query DynamoDB, o sea 1.440 req/hora por usuario con el chat abierto y 240 con la página cargada. Construirlo cuesta: API nueva en CDK, auth en `$connect` con el token de D-001, tabla de conexiones (duplicada en stack **y** `local_setup.py`), push desde `ai_worker`/`advisor` con `post_to_connection` + IAM, reconexión con backoff, **y el polling se queda igual de fallback** (redes que bloquean WS). Además rompería T5 si localstack no cubre WebSocket. Antes de eso, la mejora barata es **polling adaptativo** (rápido solo con respuesta pendiente). Revisar con números de tráfico reales de producción |
| TD-002 | Haiku vía API Anthropic directa vs Amazon Bedrock | Preguntar al equipo AWS si Bedrock está habilitado (PLAN §6.8); sin respuesta aún |
| TD-003 | Hosting frontend: Vercel vs Amplify | Sin recomendación aún; fuera del stack CDK en ambos casos |
| TD-004 | Cuentas AWS separadas stage/prod vs una sola | Separadas si el equipo AWS lo permite |
| TD-005 | `PythonFunction` (bundling) vs `DockerImageFunction` | PythonFunction mientras deps < 250 MB descomprimido |
| TD-007 | Dominio custom para la API + DNS/ACM | No bloquea MVP; URL default de API Gateway mientras tanto |
| TD-008 | ¿Gemini también clasifica, o vuelve Haiku (T9)? | **Gemini provisional** desde 2026-08-27; **modelos recalibrados 2026-09-01** contra la página oficial de precios: `gemini-3.5-flash-lite` clasifica ($0.30/$2.50 por 1M; respaldo `3.1-flash-lite`) y `gemini-3.6-flash` redacta ($1.50/$7.50; respaldo `3.5-flash` a $1.50/$9.00). Se abandonó `3.7-flash`: existe en la API pero NO figura en la tabla de precios (preview sin tarifa) y con key gratuita rechazaba sostenido ("high demand") — en la práctica todo caía al respaldo con un costo estimado inventado. Un solo proveedor = una credencial y una integración menos. Se decide con el golden set de intents: si el routing no alcanza, el tier `FAST` de `core/llm.py` vuelve a Haiku (y ahí sí aplica TD-002) |

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
  nuevo sigue este layout. `widget/logo-voyager.svg`, `widget/animation.html` y
  `widget/Anima-Bot.json` son **fuentes de referencia, no assets servidos**: `subastin.js` trae
  el wordmark de VMC calcado del SVG, el avatar animado del bot es un puerto a Canvas/WebGPU del
  efecto "Liquid Orb" de `animation.html` (decisión de producto, Aaron 2026-08-31) y el Lottie de
  `Anima-Bot.json` se descartó a propósito (cargar su runtime era más pesado) — no borrar estos
  tres archivos ni "limpiarlos" por parecer sueltos, son la fuente de verdad visual.
- Estado por fase: **F1 (chat + identidad + persistencia) implementada** —
  `core/{config,aws,auth,clock,jobs}.py`, `conversations/*`, `api/routers/chat.py`, `widget/`.
  **Mensajería del asesor implementada** (adelanto de F5, 2026-08-27): `advisors/*`,
  `api/routers/advisor.py`, `api/dev_auth.py`; falta el módulo `tickets` (D-008) y D-010.
  **Pipeline IA implementado (F2+F3, 2026-08-28)**: `workers/ai_worker.py` compone debounce
  (D-020) → triviales (D-006) → clasificador (reglas→Gemini, TD-008) → RAG/redacción → handoff
  mínimo, con registro en `AIUsage` (`agent/usage.py`); el bot responde (local:
  `scripts/run_ai_worker.py`). **Guardrails y golden set (D-024..D-026, 2026-08-28)**:
  `agent/guardrails.py` (entrada y salida), `tests/golden/intents.jsonl`, `scripts/eval_intents.py`.
  `RAG_MIN_SCORE` calibrado en `0.84` (2026-08-28, ver "RAG" abajo). Falta correr la eval real
  de intents y anotar el score base, la notificación Slack (D-016) y el ticket al derivar
  (D-008). El resto (`tickets`, `catalog`,
  `images`, `notifications`, `routers/dashboard.py`, `workers/notify_worker.py`) son stubs con
  docstrings que indican qué D-xxx los bloquea; se implementan fase por fase (PLAN.md §8) cuando
  el usuario lo pida, no por adelantado.
- Python ≥ 3.12. Imágenes nunca en DynamoDB (S3 + metadata). Datos VMC solo lectura (RF-051).
- Deps: `backend/requirements.txt` es lo que CDK bundlea en las Lambdas; `pyproject.toml` es el
  entorno local de dev — mantener ambos en sync al agregar una dependencia.
- Locales y **no versionados** (`.gitignore`): `my-usage.md` (chuleta personal), `REFERENCIA/`
  (proyecto v0 de referencia; su `.cursor/` no aplica a este repo), `data/helpcenter/*.md` y
  `chunks.json` (se regeneran con `helpcenter_fetch`). No enlazarlos desde docs versionadas.

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
- **Observabilidad (RNF-006)**: `core/observability.py` configura el logging al importar cada
  entrada (`api/main.py`, workers). Política: dev/stage `DEBUG` con vista previa del contenido;
  prod `INFO` **sin contenido** (`content_preview` devuelve solo el largo). JSON dentro de Lambda,
  texto en local. Convención: el mensaje del log es el nombre del evento (`ai.execution`,
  `ai.handoff`, `ai.debounce.skip`…) y los datos van en `extra`; `usage.record_execution` emite
  un `ai.execution` por ejecución con las mismas claves que la fila de AIUsage. La ruta
  `GET /dev/conversations/{id}/ai-usage` (`api/routers/dev.py`) alimenta la consola de
  `widget/test.html`; con `DEV_OBSERVABILITY=0` (prod) responde 404. Nunca loguear contenido
  fuera de `content_preview`. El mismo router también trae `GET /dev/tables[/{key}]` y
  `GET /dev/queues` (pestañas "Tablas"/"Cola" de `test.html`): un `scan` completo de cada tabla
  y un peek de SQS con `VisibilityTimeout=0`. Gate más estricto que `ai-usage` a propósito —
  `_solo_dev()` exige `stage == "dev"`, ni siquiera vive en stage — porque un scan expone
  mensajes de TODOS los usuarios, no solo la conversación propia.
- **`core/llm.py` — quirks por modelo de Gemini 3.x, no generalizar entre tiers**: el piso de
  `thinking_level` que acepta cada modelo varía (`ModelSpec.thinking_level`) y hay que
  **probarlo con una llamada real al cambiar de modelo** — `3.7-flash` rechazaba `"minimal"`
  con `APIError` (tumbó al redactor en local el 2026-09-01, cayendo siempre al fallback fijo
  como si no hubiera evidencia), mientras que `3.5-flash-lite`, `3.5-flash` y `3.6-flash` lo
  aceptan (sondeados 2026-09-01; con `"low"`, `3.6-flash` gastó el tope pensando y devolvió
  vacío). Cada tier lleva un respaldo (`ModelSpec.fallback`) **con su propia tarifa**: el costo
  en AIUsage se calcula con el precio del modelo que REALMENTE respondió (`llm.cost_for`),
  nunca con el del principal. Al agregar un modelo o tier nuevo, no asumir que le sirve la
  config de otro — probarlo aparte. Modelos vigentes: ver TD-008.
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
  también para una pregunta ajena al Centro de Ayuda. **Calibrado 2026-08-28 en `0.84`**
  (antes `0.75`, sin calibrar) contra el índice real: con `0.75`, preguntas totalmente ajenas a
  VMC ("¿cuánto está el dólar hoy?" → `0.835`, "receta de pastel" → `0.807`) pasaban el umbral
  y el redactor podía recibir evidencia que no venía al caso. El margen real es **angosto**
  (10 preguntas on-topic: mínimo `0.844`; 10 off-topic: máximo `0.835` — solo `0.009` de
  separación) por la compresión de similitud típica de `multilingual-e5-large` en textos
  cortos: ningún umbral separa perfectamente, y `0.84` es el mejor punto dentro de esa
  ventana con esta muestra, no un valor definitivo. Por eso la clasificación (ruteo a `OTHER`,
  RF-016) sigue siendo la primera defensa contra preguntas fuera de dominio; `RAG_MIN_SCORE`
  es el respaldo para cuando el clasificador falla o Gemini no responde (`classify()` cae a
  `FAQ` ante un `LLMError`). Re-verificar con `python -m scripts.helpcenter_upload --verify`
  si el corpus crece o si `RB-009` falla en producción.
- Los ids de chunk son estables (`hc-<artículo>-<pregunta>-<huella>`): con ids posicionales, una
  pregunta nueva corre a todas las siguientes y el upsert sobrescribe cada vector con el texto de
  otro, sin fallar. El upsert es aditivo: para un refresco completo, `--replace`.
- `frontend/` usa **Next.js 16** (App Router, React 19, Tailwind v4): APIs y convenciones difieren
  del entrenamiento — consultar `frontend/node_modules/next/dist/docs/` antes de escribir código,
  como pide `frontend/AGENTS.md`. Se despliega fuera de CDK (TD-003). Hoy las páginas de
  `src/app/advisor/` leen `src/lib/mock-data.ts`: **no están conectadas** a la API `/advisor`
  (que sí funciona en local con `ADVISOR_DEV_AUTH=1`); conectarlas es trabajo pendiente.
