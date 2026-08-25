# Subastín — plataforma de atención de VMC

Subastín reemplaza a Intercom como la plataforma propia de atención al cliente de **VMC**
(subastas de vehículos). Es un **chat web embebido en VMC** donde una IA resuelve
automáticamente lo resoluble y, cuando no debe o no puede, deriva a un **asesor humano** que
atiende desde su propia bandeja.

## ¿Qué hace?

| Quién | Qué obtiene |
|---|---|
| **Usuario anónimo** | Abre el chat sin login ni datos; FAQ y catálogo automáticos; si necesita humano, deja solo su correo |
| **Usuario autenticado en VMC** | Lo mismo, más saludo por nombre e historial asociado a su identidad VMC |
| **Asesor / CSM** | Bandeja de pendientes, "Tomar conversación" (atómica), hilo con contexto del usuario, respuesta con texto e imágenes, cierre y dashboard operativo |

**Flujo de una conversación:** el usuario escribe → **Haiku** (Anthropic) clasifica la intención
(`FAQ` / `CATALOG` / `ADVISOR` / `OTHER`) → según el caso se consulta la base de conocimiento en
**Pinecone** (RAG) o el catálogo de vehículos en **HERALD** → **Gemini** redacta la respuesta con
esa evidencia. Si no hay evidencia suficiente o el usuario pide una persona, **no se inventa
nada**: se crea un ticket, se avisa por **Slack** y la IA se apaga hasta que un asesor toma el
caso. Estados: `BOT_ATTENDING → PENDING_ADVISOR → IN_ATTENTION → CLOSED`.

Reglas no negociables: datos de VMC **solo lectura**; el bot nunca expone información financiera
ni de otros usuarios; la identidad del usuario jamás se confía al frontend.

## Arquitectura (AWS serverless, CDK v2 en Python)

```
Next.js (widget · app asesor · dashboard)
   │ HTTPS
   ▼
API Gateway HTTP API ──► Lambda `api` (FastAPI + Mangum)   ← todo lo síncrono; responde 202 y encola
   │  /advisor y /dashboard con JWT de Cognito         │
   │                                                    ▼
   │                          SQS ai-jobs ──► Lambda `worker-ai`  (Haiku → RAG / HERALD → Gemini)
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
| `frontend/` | Next.js (App Router, TypeScript, Tailwind). Se despliega fuera de CDK (Vercel/Amplify) |
| `scripts/` | Utilidades de desarrollo local: creación de tablas/colas/bucket y datos de prueba |
| `tests/` | Suite pytest, incluidas las pruebas de los patrones de acceso a DynamoDB contra servicios locales reales |
| `.github/workflows/` | `ci.yml` (lint · tests · cdk synth, sin credenciales AWS) y `deploy.yml` (CD maquetado, apagado hasta tener cuenta AWS) |
| `.claude/` | 12 skills de metodología (spec-driven, testing, commit, deploy, llm-cost-optimizer, rag-architect, prompt-governance, ci-cd, docker-dev, security-guidance, skill-auditor, write-a-skill) + hook de seguridad |

## Documentación — leer en este orden

1. **[REQUERIMENTS.md](REQUERIMENTS.md)** — el spec (fuente de verdad funcional): RF, RNF, reglas
   de negocio, criterios de aceptación, decisiones pendientes `D-xxx` y modelo DynamoDB v1.0.
2. **[PLAN.md](PLAN.md)** — la arquitectura (fuente de verdad técnica): decisiones cerradas,
   mapa de rutas → Lambdas, modelo de datos con su revisión, entornos, qué pedir al equipo AWS,
   fases.
3. **[CLAUDE.md](CLAUDE.md)** — registro vivo de decisiones abiertas/cerradas y metodología.
   Regla central: **nada que dependa de una decisión abierta se implementa asumiendo un valor.**

## Estado actual

Esqueleto pre-desarrollo: existen la estructura, la infra como código, el CI y la metodología;
**los endpoints y la lógica se implementan fase por fase** (PLAN.md §8) a medida que se cierran
las decisiones de negocio (20 `D-xxx`, responsables Silvana + Julio) y se obtiene la cuenta AWS.

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

cd frontend; npm install; cd ..
```

### Arranque diario

```powershell
docker compose up -d              # DynamoDB (:8001) + LocalStack SQS/S3 (:4566)
python -m scripts.local_setup     # crea las 5 tablas, las 2 colas y el bucket
python -m scripts.seed_data       # carga los datos de prueba

uvicorn backend.api.main:app --reload --port 8000
```

- API y documentación interactiva: **<http://localhost:8000/docs>** (Swagger UI, con botón
  *Try it out* para lanzar llamadas). Hoy solo publica `GET /health`: los endpoints se
  implementan fase por fase.
- Frontend (en otra terminal): `cd frontend; npm run dev` → <http://localhost:3000>
- Al terminar: `Ctrl+C` y `docker compose down`.

Los dos scripts son idempotentes y **hay que volver a ejecutarlos cada vez que se reinician los
contenedores**: DynamoDB local corre en memoria y pierde las tablas al apagarse.

### Verificar que todo está bien

```powershell
python -m ruff check .
python -m pytest -q               # 18 pruebas, las mismas que corre el CI
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

Nota sobre `.env`: la plantilla `.env.example` es para cuando el código de la aplicación necesite
configuración (los mismos nombres de variable que inyecta CDK en AWS). Los scripts y las pruebas
de hoy funcionan sin ella.

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
