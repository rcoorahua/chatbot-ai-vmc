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

## Desarrollo local (sin cuenta AWS)

```bash
docker compose up -d            # dynamodb-local (:8001) + localstack sqs/s3 (:4566)
python -m venv .venv            # luego activar: .venv\Scripts\activate (Windows)
pip install -e ".[dev]"         # entorno local (las Lambdas bundlean backend/requirements.txt)
cp .env.example .env            # y completar (los valores de dev están en los comentarios)

python -m scripts.local_setup   # crea las 5 tablas, las 2 colas y el bucket
python -m scripts.seed_data     # carga conversaciones, mensajes, tickets y consumo de IA de prueba

python -m ruff check . && python -m pytest -q
# cuando la API exista: uvicorn backend.api.main:app --reload --port 8000
```

Ambos scripts son idempotentes. DynamoDB local corre en memoria, así que **hay que volver a
ejecutarlos cada vez que se reinician los contenedores**.

Los datos de prueba reproducen los cuatro estados de conversación del spec —bot atendiendo,
esperando asesor, en atención y cerrada— con sus mensajes, eventos de auditoría, una imagen,
tickets y registros de consumo de IA. `tests/test_dynamo_queries.py` los usa para verificar
cada patrón de acceso contra DynamoDB real: si un índice estuviera mal definido, falla ahí y no
en producción.

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
