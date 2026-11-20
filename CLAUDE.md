# CLAUDE.md

Subastín (chatbot-ai-vmc): plataforma de atención propia de VMC que reemplaza a Intercom. Chat
web con IA (Gemini clasifica y redacta —TD-008—, RAG en Pinecone, catálogo HERALD) y handoff a
asesores humanos. AWS serverless (API Gateway HTTP API + Lambda + SQS + DynamoDB), CDK v2 Python.

Fuentes de verdad (`docs/`): **funcional** [REQUERIMENTS.md](docs/REQUERIMENTS.md) (RF/RNF/RB/AC/D
+ modelo DynamoDB) · **arquitectura** [PLAN.md](docs/PLAN.md) · **tickets y dependencias**
[BACKLOG.md](docs/BACKLOG.md) (consultarlo al planear o repartir trabajo) · **decisiones completas**
[DECISIONES.md](docs/DECISIONES.md) · **estado por fase** [ESTADO.md](docs/ESTADO.md) · flujos e
intenciones [MAPEO.md](docs/MAPEO.md) · prueba manual [TEST.md](docs/TEST.md) (demuestra que nada se
rompió, no que el FAQ responda bien) · benchmark de recuperación sin Gemini
[BENCHMARK.md](docs/BENCHMARK.md) (línea base 2026-09-03: recall 84%, rechazo 90%).
Reglas por tema en `.claude/rules/` (cargan solas al tocar los archivos de su `paths:`).

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
python -m scripts.local_setup     # crea las 6 tablas, 2 colas y el bucket — idempotente
python -m scripts.seed_data       # dataset base de las pruebas de lectura
python -m scripts.reset_local     # borra+recrea tablas, purga colas y reseedea — SIN tocar Docker
uvicorn backend.api.main:app --reload --port 8000   # http://localhost:8000/docs
cd widget; python -m http.server 8080                # widget: http://localhost:8080/test.html

python -m scripts.helpcenter_fetch                   # Centro de Ayuda -> data/helpcenter/*.md + chunks.json
python -m scripts.helpcenter_upload --verify "cuanto es la comision"   # sube a Pinecone e imprime scores (calibra RAG_MIN_SCORE); --replace = refresco completo
python -m scripts.advisor_token --sub sub-ana-001 --name "Ana Torres"   # Bearer para /advisor en local (ADVISOR_DEV_AUTH=1)
python -m scripts.run_ai_worker                      # el bot responde en local (worker contra la cola de localstack; pide GEMINI_API_KEY)
#   ⚠️ NO se recarga solo: tras tocar agent/, workers/ o conversations/ hay que REINICIARLO.
#   `uvicorn --reload` sí recoge los cambios de la API, y esa asimetría hace creer que un
#   arreglo "no funcionó" cuando lo que responde es el proceso viejo (pasó el 2026-09-02).
python -m scripts.eval_intents                       # eval REAL del golden set contra Gemini (~1 centavo); obligatoria al tocar agent/prompts.py o heuristics.py
python -m scripts.eval_retrieval                     # benchmark de RECUPERACION contra Pinecone (121 casos, SIN Gemini); obligatorio al tocar corpus/indice/umbral/agent/rag.py — ver BENCHMARK.md

python -m pytest -q                                  # suite completa (lo que corre el CI)
python -m pytest tests/test_dynamo_queries.py -q     # un archivo
python -m pytest -k "gsi1" -q                        # un patrón / una prueba
python -m ruff check .            # lint (line-length 100, reglas E/F/I/UP/B)
node widget/build.mjs             # regenera widget/subastin.js desde widget/src/*.js
node widget/build.mjs --check     # falla si el bundle quedo viejo (lo corre el CI)
node --check widget/subastin.js   # sintaxis del widget (no tiene tests)

cd infra; npx -y aws-cdk@2 synth -c stage=stage      # valida la infra sin desplegar (lo corre el CI)
cd infra; npx -y aws-cdk@2 watch -c stage=stage      # hotswap del código Lambda (~3 s); cambios de infra = deploy
cd frontend; npm run dev                             # Next.js 16 en :3000
cd frontend; npm run lint; npm run build             # eslint + build de producción
```

`local_setup` y `seed_data` se **re-ejecutan tras cada reinicio de contenedores** (dynamodb-local
corre `-inMemory`). `reset_local` limpia sin reiniciar Docker (tablas + seed + colas); el worker de
IA no necesita reiniciarse por eso (no guarda estado entre jobs).

Tests contra **dynamodb-local real**, no mocks: sin contenedores se saltan en local pero **fallan
duro en CI** (variable `CI`). Convenciones de la suite y andamiaje compartido (`tests/helpers/`,
fixtures de `conftest.py`, `limpiar`, nunca mutar el seed): `.claude/rules/tests.md`.

CI (`.github/workflows/ci.yml`): ruff + `node --check` + `build.mjs --check` + tests (dynamodb-local
2.5.2 y localstack 3.7, mismos tags que `docker-compose.yml`) + `cdk synth` + lint/build del
frontend, sin credenciales AWS. CD (`deploy.yml`) **apagado** (`if: false`) hasta tener cuenta AWS
(PLAN.md §6); `infra/config.py` lleva `account=None` a propósito.

Hook local obligatorio al clonar: `git config core.hooksPath .githooks` (bloquea push directo a
`main`/`develop`; escape hatch `ALLOW_DIRECT_PUSH=1`).

## Metodología (skills en `.claude/skills/`)

- **spec-driven** antes de implementar (RF/AC, D/TD abiertas, criterio de aceptación primero).
- **testing** después: suite COMPLETA en verde + ampliar tests a lo nuevo (default sí).
- **commit**: pull develop → rama `feature/`/`fix/` → implementar → tests → push → PR a `develop`
  (nunca push directo). `develop` = trunk (→ stage), `main` = prod protegida (PR de release).
  Conventional Commits con `Implementa RF-xxx` / `Cierra D-xxx`.
- **deploy**: CDK stage/prod con precondiciones; prod solo con confirmación explícita.
- Por tema: `llm-cost-optimizer` (toda llamada IA) · `rag-architect` · `prompt-governance`
  (cambios a `agent/prompts.py`) · `ci-cd` · `docker-dev` · `security-guidance` (RNF-005/RF-052) ·
  `skill-auditor` (skills de terceros ANTES de instalar) · `write-a-skill`.
- Hook `.claude/hooks/security_reminder_hook.py` (PreToolUse Edit/Write) bloquea anti-patrones.

## ⛔ REGLA PRINCIPAL — leer antes de implementar cualquier cosa

**Si lo que se va a implementar depende de una decisión abierta (D-xxx o TD-xxx, tablas de abajo):
DETENERSE y avisar al usuario** ("aguanta — esto depende de D-xxx que sigue abierta") en vez de
asumir un valor. Ningún pendiente se convierte en supuesto técnico oculto. Cuando el usuario cierre
una decisión: moverla a "cerradas" en `docs/DECISIONES.md`, actualizar su línea aquí y reflejarla
en PLAN.md. Antes de tocar el comportamiento de una decisión cerrada, leer su texto completo allí.

## Decisiones técnicas cerradas (no re-discutir)

T1 HTTP API (v2), no REST; JWT authorizer de Cognito para `/advisor` y `/dashboard` · T2 FastAPI en
UNA Lambda con Mangum (`lifespan="off"`), ruta `$default` · T3 workers SQS en Lambdas aparte
(`worker-ai`, `worker-notify`), la API encola y responde 202, workers devuelven `batchItemFailures`
· T4 CDK v2 Python, un stack por stage (`-c stage=stage|prod`) · T5 dev = Docker local sin cuenta
AWS; stage/prod = CDK · T6 FastAPI se queda · T7 datos/estados/código en inglés, UI y docs en
español · T8 IA asíncrona (202 + SQS + polling) · T9 superada provisionalmente por TD-008 (Gemini
en ambas etapas; Haiku `claude-haiku-4-5` es plan B para clasificar).
Modelo de datos: tablas DynamoDB de PLAN.md §4 (+ `RateLimits` de D-027). `visibility_timeout` de
cada cola ≥ 6× el timeout de su worker. Los GSI se deciden ANTES de crear tablas en stage.

## Decisiones de NEGOCIO cerradas — resumen (texto completo en docs/DECISIONES.md)

Donde choquen manda la más nueva: D-029 revisa D-002/003/017/019/023; D-031 revisa la parte anónima
de D-029 y el badge de D-030.
- **D-001** identidad: JWT HS256 firmado por VMC (`VMC_IDENTITY_SECRET`) en
  `window.subastinSettings.userJwt`, se canjea en `POST /chat/sessions` por token propio
  (`SESSION_SIGNING_KEY`). Las cookies de VMC son HttpOnly. El asistente se llama "Subastín".
- **D-002/D-003/D-029** autenticado: un hilo permanente (`THREAD`, id determinista) + hasta 5 casos
  (`CASE`) por formulario; el caso es la conversación escalada; cerrar un caso lo deja `CLOSED`, el
  hilo vuelve al bot con `TICKET_CLOSED`. **D-018** (provisional) anónimo = pestaña, token 24 h.
- **D-031** anónimo = solo FAQ y solo bot: sin formulario ni handoff, ningún asesor lo toma (409);
  al pedir asesor/agotar cuota recibe botón "Iniciar sesión" (`LINKS`, `VMC_LOGIN_URL` mock). Sin
  botón de asesor en la UI. **Rev. 2026-09-08**: con evidencia NO se ofrece asesor; solo si el
  usuario lo pide o sin evidencia (`HANDOFF_CONFIRM` sí/no). `is_advisor_click` se conserva.
- **D-004** contexto IA = últimos 20 mensajes de la última hora, sin resumen.
- **D-005** 500 caracteres/mensaje, 10 msg/min/conversación (429 + `Retry-After`), imágenes 5 MB,
  3/mensaje, 20/hora, JPG/PNG/WebP; sin tope acumulativo.
- **D-006** saludo/gracias/repetido (<10 min) → respuesta fija sin IA. **D-007** IA OFF en handoff,
  no se re-enciende sola, sin autocierre. **D-020** debounce 6 s vía `DelaySeconds`.
- **D-021** auto-alta de asesores `ACTIVE` al primer login Cognito. **D-022** solo responde quien tomó
  (toma atómica; tomar apaga el bot). **D-023** cierre sin ticket devuelve al bot.
- **D-024** manipulación/datos de otros → respuesta fija, sin IA ni derivar; salida con cifra/enlace
  fuera de evidencia o fuga del prompt → se descarta y deriva como "sin evidencia".
- **D-025/D-030** tono peruano cercano, máx. un emoji (nunca junto a cifras/enlaces), negritas
  `**así**` permitidas, sin URLs en el texto. **D-030**: respuesta completa por pregunta, no cierra
  preguntando si continuar, estado de cuenta en `<usuario>` (nunca pregunta "¿tienes cuenta?"),
  fuente como chip, hasta 3 preguntas hermanas sin estado.
- **D-026** golden set; cambio de prompt exige eval real ≥ 95% (`scripts.eval_intents`).
- **D-027** cuota de IA: anónimo 10/h y 20/día (sesión e IP hasheada), autenticado 20/h y 40/día;
  solo cuenta lo que llamó a un modelo; `0 = ilimitado` y así en dev.
- **D-028** flujos guiados con quick replies (5 activos), estado liviano en Conversations, botones
  validados en servidor, consulta canónica al RAG; sin LangGraph.
- **D-010** del JWT se guardan CUU (solo para mostrar, nunca credencial), `user_id` y correo; el
  nombre no viene de VMC.

## Decisiones abiertas — NO asumir valores (detalle en docs/DECISIONES.md)

Negocio (Silvana + Julio): **D-008** taxonomía de tickets (propuesta implementada en
`backend/tickets/taxonomy.py`, sigue abierta) · **D-009** tags · **D-011** contrato HERALD (F4) ·
**D-012** fallback HERALD caído · **D-013** métricas dashboard (F7) · **D-014** retención/TTL ·
**D-015** imágenes para IA (F6) · **D-016** Slack (worker-notify).
Técnicas: **TD-001** polling vs WebSocket (sigue polling adaptativo) · **TD-002** Haiku vía Anthropic
vs Bedrock · **TD-003** hosting frontend · **TD-004** cuentas AWS separadas · **TD-005**
PythonFunction vs DockerImageFunction · **TD-007** dominio custom · **TD-008** Gemini también
clasifica (provisional) · **TD-010** reranker como decisor de evidencia (`--rerank` es solo medición).

## Convenciones y layout

- `backend/` = **monolito modular** con dependencias en UNA dirección (`backend/__init__.py`):
  entradas (`api/`, `workers/`) → dominio (`conversations`, `tickets`, `advisors`) → integraciones
  hoja (`agent`, `catalog`, `notifications`, `images`) → `core`. El dominio NUNCA importa
  integraciones; la composición vive en la entrada. Cada `repository.py` es el único que conoce
  claves/GSIs. Infra en `infra/`, app del asesor en `frontend/`, widget en `widget/`.
- Los stubs (`catalog`, `images`, `notifications`, `routers/dashboard.py`,
  `workers/notify_worker.py`) se implementan cuando el usuario lo pida, no por adelantado.
- Python ≥ 3.12. Imágenes nunca en DynamoDB (S3 + metadata). Datos VMC solo lectura (RF-051).
- Docs nuevos van a `docs/`; en la raíz solo `README.md`, `DEPLOYMENT.md` (lo lee el equipo AWS),
  `CLAUDE.md` y `DETAILS.md`. Las menciones sin enlace ("PLAN.md §6") siguen valiendo.
- Locales y no versionados: `my-usage.md`, `REFERENCIA/` (v0; su `.cursor/` no aplica),
  `data/helpcenter/*.md`, `chunks.json`. No enlazarlos desde docs versionadas.
- TD-006 cerrada: la v0 se eliminó; backup en `../chatbot-ai-vmc-v0-backup.zip`.

**Invariantes que cruzan archivos** (el linter no los ve; detalle en `.claude/rules/`):
esquema DynamoDB, TTL y colas duplicados en stack **y** `local_setup.py` · mismos nombres de env
var en stack, `local_setup` y `.env.example` · errores HTTP solo en `api/errors.py`, ningún router
importa un `repository` · secretos por Secrets Manager en runtime, nunca env del stack · dos secretos
de identidad, nunca unificarlos · id determinista del hilo (`uuid5`) · listados acotan SK con `"3"`
por los `CMID#` · nunca loguear contenido fuera de `content_preview`.
