# Subastín — plataforma de atención de VMC

Subastín reemplaza a Intercom como la plataforma propia de atención al cliente de **VMC**
(subastas de vehículos). Es un **chat web embebido en VMC** donde una IA resuelve
automáticamente lo resoluble y, cuando no debe o no puede, deriva a un **asesor humano** que
atiende desde su propia bandeja.

## ¿Qué hace?

| Quién | Qué obtiene |
|---|---|
| **Usuario anónimo** | Abre el chat sin login ni datos; FAQ y catálogo automáticos, y su conversación dura lo que la pestaña. Para hablar con un asesor tiene que crear una cuenta gratis en VMC (D-002/D-031): el bot se lo dice y le da el botón |
| **Usuario autenticado en VMC** | Lo mismo, más saludo por nombre y **una conversación permanente** asociada a su identidad VMC; los tickets son el historial y se cierran dentro del hilo (D-003) |
| **Asesor / CSM** | Bandeja de pendientes, "Tomar conversación" (atómica), hilo con contexto del usuario, respuesta con texto e imágenes, cierre y dashboard operativo |

**Flujo de una conversación:** el usuario escribe → **Gemini flash-lite** clasifica la intención
(`FAQ` / `CATALOG` / `ADVISOR` / `OTHER`; Haiku es el plan B, TD-008) → según el caso se consulta
la base de conocimiento en **Pinecone** (RAG) o el catálogo de vehículos en **HERALD** →
**Gemini** redacta la respuesta con esa evidencia. Si no hay evidencia suficiente o el usuario pide una persona, **no se inventa
nada**: se crea un ticket, se avisa por **Slack** y la IA se apaga hasta que un asesor toma el
caso. Estados: `BOT_ATTENDING → PENDING_ADVISOR → IN_ATTENTION → CLOSED`.

Reglas no negociables: datos de VMC **solo lectura**; el bot nunca expone información financiera
ni de otros usuarios; la identidad del usuario jamás se confía al frontend.

## Arquitectura (AWS serverless, CDK v2 en Python)

```
widget/ (JS embebido en VMC) · Next.js (app asesor · dashboard)
   │ HTTPS
   ▼
API Gateway HTTP API ──► Lambda `api` (FastAPI + Mangum)   ← todo lo síncrono; responde 202 y encola
   │  /chat con JWT de identidad de VMC + token de sesión   │
   │  /advisor y /dashboard con JWT de Cognito             │
   │                                                    ▼
   │                          SQS ai-jobs ──► Lambda `worker-ai`  (clasifica → RAG / HERALD → redacta)
   │                          SQS notifications ──► Lambda `worker-notify` (Slack)
   ▼
DynamoDB (Conversations · Messages · Tickets · Advisors · AIUsage) · S3 (imágenes) · Cognito
Secrets Manager · CloudWatch
```

La respuesta de la IA es asíncrona (el frontend hace polling): desacopla la latencia de los
modelos del request HTTP y habilita reintentos, DLQs y debounce. El backend es un **monolito
modular** con dependencias en una sola dirección (regla en `backend/__init__.py`).

## Estructura del repositorio

| Carpeta | Contenido |
|---|---|
| `backend/` | Código de las Lambdas. Entradas delgadas (`api/`, `workers/`) → dominio (`conversations`, `tickets`, `advisors`) → integraciones hoja (`agent`, `catalog`, `notifications`, `images`) → `core` |
| `infra/` | Stacks CDK v2 (Python): tablas, colas, Lambdas, HTTP API, Cognito, S3. Un stack por stage (`-c stage=stage` o `prod`) |
| `widget/` | El chat que se embebe en VMC: `subastin.js` (JS plano, sin build), `test.html` para probarlo en local y el contrato de identidad para VMC (`README.md`) |
| `frontend/` | Next.js (App Router, TypeScript, Tailwind) para la app del asesor y el dashboard. Se despliega fuera de CDK (Vercel/Amplify) |
| `scripts/` | Utilidades locales: tablas/colas/bucket, datos de prueba y la ingesta del Centro de Ayuda a Pinecone (`helpcenter_fetch` → `helpcenter_upload`) |
| `data/helpcenter/` | El conocimiento del bot: markdown descargado del Centro de Ayuda y sus chunks. No se versiona (se regenera con un comando) — ver su [README](data/helpcenter/README.md) |
| `tests/` | Suite pytest, incluidas las pruebas de los patrones de acceso a DynamoDB contra servicios locales reales |
| `.github/workflows/` | `ci.yml` (lint · tests · cdk synth, sin credenciales AWS) y `deploy.yml` (CD maquetado, apagado hasta tener cuenta AWS) |
| `.claude/` | 12 skills de metodología (spec-driven, testing, commit, deploy, llm-cost-optimizer, rag-architect, prompt-governance, ci-cd, docker-dev, security-guidance, skill-auditor, write-a-skill) + hook de seguridad |
| `docs/` | Toda la documentación salvo tres archivos que viven en la raíz a propósito: este `README.md`, `CLAUDE.md` (registro vivo de decisiones, lo lee Claude Code al arrancar) y `DETAILS.md` (auditoría técnica P0/P1 con su estado) |

## Documentación — leer en este orden

1. **[REQUERIMENTS.md](docs/REQUERIMENTS.md)** — el spec (fuente de verdad funcional): RF, RNF, reglas
   de negocio, criterios de aceptación, decisiones pendientes `D-xxx` y modelo DynamoDB v1.0.
2. **[PLAN.md](docs/PLAN.md)** — la arquitectura (fuente de verdad técnica): decisiones cerradas,
   mapa de rutas → Lambdas, modelo de datos con su revisión, entornos, qué pedir al equipo AWS,
   fases.
3. **[CLAUDE.md](CLAUDE.md)** — registro vivo de decisiones abiertas/cerradas y metodología.
   Regla central: **nada que dependa de una decisión abierta se implementa asumiendo un valor.**
4. **[BACKLOG.md](docs/BACKLOG.md)** — el trabajo dividido en tickets tomables, con sus dependencias:
   qué se puede empezar hoy, qué bloquea cada decisión pendiente y cómo repartirlo entre dos
   personas sin pisarse.
5. **[MAPEO.md](docs/MAPEO.md)** — qué intenciones del Centro de Ayuda llevan flujo guiado con
   botones y cuáles son FAQ planas (D-028), y la taxonomía de tickets propuesta para D-008.
6. **[TEST.md](docs/TEST.md)** — prueba manual del bot: comandos para levantar y resetear el
   entorno, 50 mensajes sueltos y 30 conversaciones. Demuestra que nada se rompió, no que el
   FAQ responda bien.
7. **[BENCHMARK.md](docs/BENCHMARK.md)** — benchmark de recuperación del FAQ contra Pinecone
   (121 consultas, sin Gemini): recall y rechazo con números comparables entre versiones.
8. **[DETAILS.md](DETAILS.md)** — auditoría técnica (P0/P1) con el estado de cada hallazgo.

También en `docs/`: `DESIGN.md` (sistema de diseño del panel del asesor: tokens, tipografía,
componentes) y `PRODUCT.md` (brief de producto del panel).

## Estado actual

**F1 implementada (2026-08-27)**: chat público con identidad VMC (`POST /chat/sessions`),
persistencia idempotente de mensajes, sondeo, y el widget embebible con su página de prueba.

**Pipeline IA completo (2026-08-28): el bot responde.** `workers/ai_worker.py` encadena debounce
(D-020) → triviales (D-006) → guardrails de seguridad (D-024: manipulación y datos de terceros,
sin IA) → clasificador (reglas → Gemini flash-lite, TD-008) → RAG en Pinecone + redacción con
Gemini → verificación de la respuesta contra la evidencia (cifras, enlaces, fuga del prompt) →
handoff mínimo. Toda decisión queda en `AIUsage`. Los prompts tienen golden set
(`tests/golden/intents.jsonl`) y eval real a mano (`python -m scripts.eval_intents`, D-026).
En local: `python -m scripts.run_ai_worker` con `GEMINI_API_KEY`, `PINECONE_API_KEY` y
`AI_JOBS_QUEUE_URL` en `.env`.

**Mensajería del asesor (2026-08-27)**: `/advisor/*` con bandeja, toma atómica, hilo, respuesta
y cierre mínimo; la app Next.js aún usa datos de prueba. El resto (tickets, Slack, catálogo,
imágenes, dashboard) se implementa fase por fase (PLAN.md §8) a medida que se cierran las
decisiones de negocio pendientes (responsables Silvana + Julio) y se obtiene la cuenta AWS.

## Cómo correr el proyecto (local, sin cuenta AWS)

Requisitos: **Docker Desktop**, **Python 3.12**, **Node 22** (solo para el frontend) y,
opcionalmente, **AWS CLI** si quieres consultar los datos a mano.

### Instalación (una sola vez)

```powershell
git clone https://github.com/rcoorahua/chatbot-ai-vmc.git
cd chatbot-ai-vmc
git config core.hooksPath .githooks     # bloquea pushes directos a main/develop

python -m venv .venv
.venv\Scripts\Activate.ps1               # Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"

Copy-Item .env.example .env              # y poner VMC_IDENTITY_SECRET y SESSION_SIGNING_KEY
                                         # (cualquier texto en dev; el widget de prueba usa
                                         # "dev-vmc-identity-secret" por defecto)
cd frontend; npm install; cd ..
```

### Arranque diario

```powershell
docker compose up -d              # DynamoDB (:8001) + LocalStack SQS/S3 (:4566)
python -m scripts.local_setup     # crea las 6 tablas, las 2 colas y el bucket
python -m scripts.seed_data       # carga los datos de prueba

uvicorn backend.api.main:app --reload --port 8000
python -m scripts.run_ai_worker                      # en otra terminal: el bot responde (pide GEMINI_API_KEY en .env)
```

- API y documentación interactiva: **<http://localhost:8000/docs>** (Swagger UI, con botón
  *Try it out* para lanzar llamadas). Publica `GET /health` y el chat público `/chat/*`
  (sesiones, conversación, mensajes); el resto se implementa fase por fase.
- **Widget** (en otra terminal): `cd widget; python -m http.server 8080` →
  <http://localhost:8080/test.html>, que simula la página de VMC en modo anónimo o autenticado.
  Detalle en [widget/README.md](widget/README.md).
- **Consola de observabilidad** en la misma `test.html`: por cada mensaje muestra qué capa
  decidió (trivial, guardrail, regla o modelo), el modelo, los tokens, el costo y la latencia,
  leyendo `GET /dev/conversations/{id}/ai-usage` (solo dev/stage; 404 en prod). Los logs de la
  terminal siguen la misma política: `LOG_LEVEL`/`LOG_CONTENT` vacías = detallado en dev.
- App del asesor: `cd frontend; npm run dev` → <http://localhost:3000> (hoy con datos de prueba).
  La API `/advisor/*` ya funciona en local: pon `ADVISOR_DEV_AUTH=1` y `ADVISOR_DEV_JWT_SECRET=algo`
  en `.env`, emite un token con `python -m scripts.advisor_token --sub sub-ana-001 --name "Ana"`
  y úsalo como `Authorization: Bearer …` (en AWS ese papel lo hace el authorizer de Cognito).
- **Conocimiento del bot** (solo cuando cambie el Centro de Ayuda):
  `python -m scripts.helpcenter_fetch` y luego `python -m scripts.helpcenter_upload --verify`.
  Necesita `PINECONE_API_KEY`; no usa Gemini (Pinecone genera los embeddings).
- Al terminar: `Ctrl+C` y `docker compose down`.

Los dos scripts son idempotentes y **hay que volver a ejecutarlos cada vez que se reinician los
contenedores**: DynamoDB local corre en memoria y pierde las tablas al apagarse. Para limpiar
lo que ensuciaron pruebas manuales sin reiniciar los contenedores, `python -m scripts.reset_local`
hace las dos cosas en un solo paso (y purga las colas); no hace falta reiniciar el worker de IA.

### Verificar que todo está bien

```powershell
python -m ruff check .
python -m pytest -q               # ~175 pruebas, las mismas que corre el CI
node --check widget/subastin.js   # sintaxis del widget
```

### Consultar los datos a mano (AWS CLI)

Los scripts y las pruebas **no necesitan configuración**: traen los valores locales por defecto.
El AWS CLI sí pide credenciales, así que se configura **un perfil una sola vez** — más fiable que
exportar variables en cada terminal, y deja los comandos cortos:

```powershell
aws configure set profile.subastin-local.region us-east-1
aws configure set profile.subastin-local.aws_access_key_id local
aws configure set profile.subastin-local.aws_secret_access_key local
aws configure set profile.subastin-local.services subastin-local-endpoints
```

Y añade este bloque al final de `~/.aws/config` (así el CLI apunta solo a los contenedores y no
hay que escribir `--endpoint-url` en cada comando):

```ini
[services subastin-local-endpoints]
dynamodb =
  endpoint_url = http://localhost:8001
sqs =
  endpoint_url = http://localhost:4566
s3 =
  endpoint_url = http://localhost:4566
```

Hecho eso, todos los comandos son de esta forma:

```powershell
# Ver el contenido completo de cada tabla
aws --profile subastin-local dynamodb scan --table-name subastin-dev-conversations --query 'Items[].[conversation_id.S,status.S,user_name.S,assigned_advisor_id.S]' --output table
aws --profile subastin-local dynamodb scan --table-name subastin-dev-messages      --query 'Items[].[conversation_id.S,created_at.S,sender_type.S,content.S]' --output table
aws --profile subastin-local dynamodb scan --table-name subastin-dev-tickets       --query 'Items[].[ticket_id.S,conversation_id.S,status.S,handoff_reason.S]' --output table
aws --profile subastin-local dynamodb scan --table-name subastin-dev-advisors      --query 'Items[].[advisor_id.S,name.S,status.S,cognito_sub.S]' --output table
aws --profile subastin-local dynamodb scan --table-name subastin-dev-ai-usage      --query 'Items[].[conversation_id.S,execution_type.S,provider.S,estimated_cost_usd.N]' --output table

# Una conversación por su id
aws --profile subastin-local dynamodb get-item --table-name subastin-dev-conversations --key '{\"conversation_id\":{\"S\":\"conv_002\"}}' --output json

# La bandeja del asesor (índice gsi2_inbox; `status` es palabra reservada, de ahí el alias #s)
aws --profile subastin-local dynamodb query --table-name subastin-dev-conversations --index-name gsi2_inbox --key-condition-expression "#s = :e" --expression-attribute-names '{\"#s\":\"status\"}' --expression-attribute-values '{\":e\":{\"S\":\"PENDING_ADVISOR\"}}' --output table

# El hilo de mensajes de una conversación, en orden cronológico
aws --profile subastin-local dynamodb query --table-name subastin-dev-messages --key-condition-expression "conversation_id = :c" --expression-attribute-values '{\":c\":{\"S\":\"conv_002\"}}' --query 'Items[].[created_at.S,sender_type.S,content.S]' --output table
```

> **En macOS y Linux** quita las barras invertidas de los JSON: PowerShell las necesita para
> escapar las comillas, bash no. Por ejemplo `--key '{"conversation_id":{"S":"conv_002"}}'`.

`scan` lee la tabla entera: sirve para explorar en local, pero el código de la aplicación siempre
usa `query` sobre una clave o un índice — que es justo lo que verifican las pruebas.

Nota sobre `.env`: la API lo lee al arrancar (mismos nombres de variable que inyecta CDK en AWS).
Los scripts y las pruebas funcionan sin él — las pruebas fijan secretos de prueba por su cuenta —
pero `uvicorn` responde 503 en `/chat/sessions` si faltan `VMC_IDENTITY_SECRET` o
`SESSION_SIGNING_KEY`.

### Si algo falla

| Síntoma | Solución |
|---|---|
| `ModuleNotFoundError` | Falta activar el entorno: `.venv\Scripts\Activate.ps1` |
| Las pruebas no encuentran las tablas | `docker compose up -d` y volver a correr `scripts.local_setup` |
| `WinError 10013` o *address already in use* al arrancar uvicorn | El puerto está ocupado: `Get-NetTCPConnection -LocalPort 8000 \| Select OwningProcess` y `Stop-Process -Id <id> -Force`, o usar `--port 8080` |
| Errores de Docker en CDK | Docker Desktop no está corriendo |
| Rechazo al hacer push a `develop`/`main` | Es correcto: hay que abrir un pull request |

## Flujo de trabajo

Trunk-Based Development adaptado + Conventional Commits (detalle en `.claude/skills/commit`):

```
feature/<slug> · fix/<slug>  ──PR──►  develop  ──deploy──►  stage
                                         │
                                    PR de release
                                         ▼
                                        main  ──deploy──►  prod (gate manual)
```

Cada cambio nace de un requerimiento del spec, trae sus tests y pasa el CI antes de integrarse.
Un hook local impide pushes directos a `main`/`develop` — actívalo al clonar:

```bash
git config core.hooksPath .githooks
```

---

La v0 (monolito WhatsApp + Gemini) fue retirada del repo; backup en
`../chatbot-ai-vmc-v0-backup.zip`.
