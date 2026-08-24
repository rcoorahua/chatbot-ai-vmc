# Subastín (chatbot-ai-vmc)

Plataforma de atención propia de VMC que reemplaza a Intercom: chat web con IA (Haiku clasifica,
Gemini redacta, RAG en Pinecone, catálogo HERALD) y handoff a asesores humanos. Arquitectura AWS
serverless (API Gateway HTTP API + Lambda + SQS + DynamoDB) definida con CDK v2 en Python.

> **Estado: esqueleto pre-desarrollo.** Nada está implementado todavía; los endpoints y la lógica
> se construyen fase por fase. El diseño completo está en [PLAN.md](PLAN.md) y el registro de
> decisiones (cerradas y abiertas) en [CLAUDE.md](CLAUDE.md) — **leer ambos antes de tocar código**.

## Estructura

| Carpeta | Qué es |
|---|---|
| `backend/` | Código Python de las Lambdas: `api/` (FastAPI + Mangum) y `workers/` (SQS) como entradas delgadas, módulos de dominio (`conversations`, `tickets`, `advisors`) e integraciones hoja (`agent`, `catalog`, `notifications`, `images`) sobre `core`. Regla de dependencias en `backend/__init__.py`. |
| `infra/` | Stacks CDK v2 (Python) para stage/prod. `cdk deploy -c stage=stage\|prod`. |
| `frontend/` | Next.js (App Router, TS, Tailwind) — widget de chat, app del asesor y dashboard. Se despliega fuera de CDK (Vercel/Amplify, TD-003). |

## Dev local (sin cuenta AWS)

```bash
docker compose up -d          # dynamodb-local (:8001) + localstack sqs/s3 (:4566)
pip install -e ".[dev]"       # entorno local (las Lambdas bundlean backend/requirements.txt)
cp .env.example .env
# API y workers aún no implementados; cuando existan:
#   uvicorn backend.api.main:app --reload --port 8000
```

La v0 (monolito WhatsApp + Gemini) fue retirada del repo; hay un backup en
`../chatbot-ai-vmc-v0-backup.zip`.
