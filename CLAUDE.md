# CLAUDE.md — Subastín (chatbot-ai-vmc)

Plataforma de atención propia de VMC que reemplaza a Intercom: chat web con IA
(Haiku clasifica, Gemini redacta, RAG en Pinecone, catálogo HERALD) y handoff a asesores humanos.
Arquitectura AWS serverless (API Gateway HTTP API + Lambda + SQS + DynamoDB) con CDK v2 Python.
**Fuente de verdad funcional: [REQUERIMENTS.md](REQUERIMENTS.md)** (RF/RNF/RB/AC/D + modelo
DynamoDB v1.0). **Fuente de verdad de arquitectura: [PLAN.md](PLAN.md).**

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
- **T9** Haiku = `claude-haiku-4-5` (SDK `anthropic`) para clasificación; Gemini (SDK `google-genai`) para redacción.
- Modelo de datos: 5 tablas DynamoDB (`Conversations`, `Messages`, `Tickets`, `Advisors`, `AIUsage`) — claves/GSIs en PLAN.md §4, con los ajustes 1–5 de la revisión (unread_count, wait_message_sent, TTL en Messages, idempotencia transaccional, GSI sparse opcional).
- `visibility_timeout` de cada cola ≥ 6× el timeout de su worker.
- Los GSI se deciden ANTES de crear tablas en stage (backfill posterior es migración manual).

## Decisiones de NEGOCIO abiertas (D-xxx) — responsables: Silvana + Julio

Detalle en [REQUERIMENTS.md](REQUERIMENTS.md) §6 y PLAN.md §9.

| ID | Tema | Prio | Bloquea |
|---|---|---|---|
| D-001 | Mecanismo identidad VMC ↔ Subastín (iframe/script/token/S2S) | Alta | auth del chat, embed del widget |
| D-002 | Máx. conversaciones activas (autenticado) | Alta | F1 |
| D-003 | Cierre/reapertura/historial visible + autocierre | Alta | F7, worker-maintenance |
| D-004 | Estrategia de resumen para IA | Media | pipeline IA |
| D-005 | Guardrails cuantitativos (límites, rate limit) | Alta | F1 |
| D-006 | Saludos/spam/repetición sin llamada IA | Media | F2 |
| D-007 | Duración IA OFF durante handoff | Alta | F5 |
| D-008 | Taxonomía de problemas/tickets y campos | Alta | F5, tabla Tickets (`problem_type`, `category`, `tags`) |
| D-009 | Tags de negocio | Media | Tickets |
| D-010 | Campos de usuario VMC visibles/usables | Alta | F5, vista asesor |
| D-011 | Contrato HERALD (endpoints, auth, filtros) | Alta | F4 |
| D-012 | Fallback cuando HERALD caído | Media | F4 |
| D-013 | Métricas exactas del dashboard | Media | F7 |
| D-014 | Retención (¿6 meses?) conversaciones/imágenes | Alta | TTL, S3 lifecycle |
| D-015 | Procesamiento de imágenes para IA (modelo, resize) | Media | F6 |
| D-016 | Canal Slack y formato de notificación | Baja | worker-notify |
| D-017 | Relación conversación ↔ ticket (¿N tickets?) | Alta | F5 |
| D-018 | Sesión anónima activa (duración técnica) | Media | F1 |
| D-019 | Handoff anónimo sin correo | Media | F5 |
| D-020 | Debounce/agregación de mensajes antes de IA | Media | F2 |

## Decisiones TÉCNICAS abiertas (TD-xxx)

| ID | Tema | Recomendación actual |
|---|---|---|
| TD-001 | Entrega en tiempo real: polling vs API Gateway WebSocket | Polling 2–3 s para MVP (cumple RNF-001 ≤10 s); WebSocket requeriría tabla de conexiones extra |
| TD-002 | Haiku vía API Anthropic directa vs Amazon Bedrock | Preguntar al equipo AWS si Bedrock está habilitado (PLAN §6.8); sin respuesta aún |
| TD-003 | Hosting frontend: Vercel vs Amplify | Sin recomendación aún; fuera del stack CDK en ambos casos |
| TD-004 | Cuentas AWS separadas stage/prod vs una sola | Separadas si el equipo AWS lo permite |
| TD-005 | `PythonFunction` (bundling) vs `DockerImageFunction` | PythonFunction mientras deps < 250 MB descomprimido |
| TD-007 | Dominio custom para la API + DNS/ACM | No bloquea MVP; URL default de API Gateway mientras tanto |

TD-006 **cerrada** (2026-08-24): la v0 (WhatsApp+Gemini) se eliminó del repo; backup en
`../chatbot-ai-vmc-v0-backup.zip`.

## Convenciones y layout

- Backend en `backend/` = **monolito modular** con dependencias en UNA dirección (regla completa
  en `backend/__init__.py`): entradas (`api/`, `workers/`) → dominio (`conversations`, `tickets`,
  `advisors`) → integraciones hoja (`agent`, `catalog`, `notifications`, `images`) → `core`.
  El dominio NUNCA importa integraciones; la composición vive en la entrada (p. ej. el pipeline
  IA en `workers/ai_worker.py`). Cada `repository.py` es el único que conoce claves/GSIs.
- Infra en `infra/`, frontend en `frontend/`. Todo el código nuevo sigue este layout.
- Los módulos son stubs con docstrings: **los endpoints y la lógica aún no están definidos** — se
  implementan fase por fase (PLAN.md §8) cuando el usuario lo pida, no por adelantado.
- Python ≥ 3.12. Imágenes nunca en DynamoDB (S3 + metadata). Datos VMC solo lectura (RF-051).
- Deps: `backend/requirements.txt` es lo que CDK bundlea en las Lambdas; `pyproject.toml` es el
  entorno local de dev — mantener ambos en sync al agregar una dependencia.
