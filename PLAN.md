# PLAN — Subastín MVP (reemplazo de Intercom)

> **Estado: replanteo v1.** Basado en el spec Spec-Driven del MVP y el modelo de datos de 5
> tablas acordado — ambos consolidados en el repo como [REQUERIMENTS.md](REQUERIMENTS.md). **Sustituye por completo al plan
> anterior** (monolito FastAPI con WhatsApp + Gemini); esa v0 fue **eliminada del repo** (TD-006
> cerrada) — backup en `../chatbot-ai-vmc-v0-backup.zip`.
>
> **Regla de oro:** ningún punto pendiente del spec se trata como supuesto cerrado. Antes de
> implementar cualquier cosa que dependa de una decisión abierta (`D-xxx` de negocio o `TD-xxx`
> técnica), se detiene el trabajo y se avisa. El registro vivo de decisiones está en
> [CLAUDE.md](CLAUDE.md).

---

## 1. Contexto y alcance

Subastín reemplaza a Intercom como plataforma propia de atención de **VMC**:

- **Canal único del MVP:** chat web embebido en VMC (WhatsApp/Kapso queda fuera; sin timeline
  omnicanal).
- **Usuarios:** anónimos (sin datos, sin historial persistente — RF-002/004) y autenticados
  (identidad validada por VMC — RF-005, mecanismo pendiente **D-001**).
- **Automatización:** clasificación de intención con **Haiku** (RF-015), FAQ con **RAG sobre
  Pinecone** (RF-017), catálogo de vehículos vía **API HERALD** (RF-044), redacción con **Gemini**
  (RF-020), y prohibición explícita de inventar sin evidencia (RF-018 → handoff).
- **Atención humana:** handoff → ticket → notificación **Slack** inmediata (RF-028) → bandeja de
  asesores (Cognito, rol único `ADVISOR` — RF-006/007) → toma atómica (RF-029/AC-005) → cierre.
- **Operación:** dashboard numérico básico para CSMs (RF-047/048).
- **Datos VMC: solo lectura** (RF-051); el bot no expone datos sensibles (RF-052).
- **RNF clave:** respuesta automática ≤ 10 s (RNF-001), disponibilidad 99% (RNF-002), durabilidad
  confirmada antes de mostrar como enviado (RNF-003), idempotencia (RNF-004), identidad no
  confiable desde frontend (RNF-005), observabilidad CloudWatch (RNF-006), límites anti-abuso
  (RNF-007), optimización multimodal (RNF-008).

Mapa rápido RF → componente:

| Grupo del spec | RFs | Componente responsable |
|---|---|---|
| Acceso/identidad/sesión | RF-001..007 | Frontend widget + Lambda `api` + Cognito (asesores) + integración VMC (D-001) |
| Conversaciones/mensajes/estados | RF-008..014 | Lambda `api` + DynamoDB (`Conversations`, `Messages`) |
| IA, clasificación, FAQ/RAG | RF-015..021 | Lambda `worker-ai` + Anthropic (Haiku) + Gemini + Pinecone |
| Handoff y tickets | RF-022..031 | Lambda `api` + `worker-ai` (dispara) + `Tickets` + Lambda `worker-notify` (Slack) |
| App del asesor | RF-032..039 | Frontend (app asesor) + Lambda `api` (rutas `/advisor`) |
| Imágenes | RF-040..043 | S3 (presigned URLs) + `worker-ai` (interpretación, D-015) |
| Catálogo HERALD | RF-044..046 | `worker-ai` → API HERALD (contrato D-011) |
| Dashboard | RF-047..049 | Frontend + Lambda `api` (rutas `/dashboard`) |
| Auditoría y datos VMC | RF-050..053 | Mensajes `SYSTEM` en `Messages` + TTL/retención (D-014) |

---

## 2. Arquitectura objetivo (AWS serverless)

Se abandona el contenedor uvicorn permanente. La arquitectura pasa a **API Gateway + Lambda + SQS +
DynamoDB**, definida con **CDK v2 en Python**, escala a cero y con dev 100% local.

```
                         ┌────────────────────────── AWS (stage / prod) ──────────────────────────┐
  Next.js (widget VMC    │                                                                        │
  + app asesor +         │   API Gateway HTTP API                                                 │
  dashboard)             │   ├── $default ──────────────► Lambda `api` (FastAPI + Mangum)         │
  ── fetch ────────────► │   ├── /advisor/{proxy+} ──┐    │  · valida identidad VMC (D-001)       │
                         │   │   [JWT authorizer     ├──► │  · CRUD conversaciones/mensajes       │
                         │   │    Cognito]           │    │  · presigned URLs S3 (imágenes)       │
                         │   └── /dashboard/{proxy+}─┘    │  · encola trabajos IA → SQS, 202      │
                         │                                │  · toma atómica, tickets, cierre      │
                         │                                ▼                                       │
                         │        SQS `ai-jobs` ──────► Lambda `worker-ai`                        │
                         │          └─ DLQ                │ Haiku (clasifica) → Pinecone (RAG)    │
                         │        SQS `notifications` ─►  │ → HERALD (catálogo) → Gemini (redacta)│
                         │          └─ DLQ         Lambda │ → guarda respuesta + AIUsage          │
                         │                  `worker-notify`──► Slack webhook                      │
                         │                                                                        │
                         │   DynamoDB (5 tablas) · S3 (imágenes) · Cognito (asesores)             │
                         │   Secrets Manager · CloudWatch (logs/métricas/alarmas)                 │
                         └────────────────────────────────────────────────────────────────────────┘
                              Externos: Anthropic API (Haiku) · Gemini API · Pinecone · HERALD · VMC
```

### Decisiones técnicas cerradas (el porqué)

| # | Decisión | Justificación |
|---|---|---|
| T1 | **HTTP API** (API Gateway v2), no REST API | ~1/3 del costo y menos latencia. REST API solo se justifica con usage plans/API keys, validación nativa o WAF regional; la validación la hace Pydantic. Tiene **JWT authorizer nativo contra Cognito** para las rutas de asesor. |
| T2 | **FastAPI completo en una sola Lambda con Mangum** (`$default`) | Conserva router, OpenAPI docs y dependencias compartidas; evita multiplicar cold starts. `Mangum(app, lifespan="off")` — con lifespan on, la Lambda se cuelga en startup. Se separa una función solo si tiene timeout/memoria distintos. |
| T3 | **Workers SQS en Lambdas separadas** de la API | Distinto timeout, memoria y perfil de fallo. La API solo hace `send_message` y responde 202. Los workers devuelven `{"batchItemFailures": [...]}` (formato exacto, si no SQS lo ignora). |
| T4 | **CDK v2 en Python** para infra | Mismo lenguaje que el backend; constructs L2 + `grant_*` generan las políticas IAM sin JSON manual. Es exactamente el patrón APIGW+Lambda+SQS+DynamoDB donde CDK ahorra más. |
| T5 | **dev = local con Docker** (sin cuenta AWS); **stage y prod = stacks CDK separados** | Loop de desarrollo sin costo ni credenciales; `cdk watch` para iterar en stage. |
| T6 | **FastAPI se mantiene** como framework del backend | Compatible con la arquitectura Lambda vía Mangum (patrón estándar y soportado); no hay razón para cambiar de framework. |
| T7 | **Estados y atributos de datos en inglés** (`PENDING_ADVISOR`…), UI en español | El spec los nombra en español (`PENDIENTE_ASESOR`) pero el modelo de datos acordado ya está en inglés; el mapeo a texto visible vive solo en el frontend. |
| T8 | **Respuesta IA asíncrona**: POST → 202 + job SQS; el frontend obtiene la respuesta por polling | Desacopla la latencia de IA (varios segundos) del request HTTP; habilita debounce (D-020), reintentos y DLQ. Cumple RNF-001 (≤10 s) con polling de 2–3 s. |
| T9 | **Modelos IA**: clasificación/orquestación con Anthropic **Haiku** (`claude-haiku-4-5`, SDK `anthropic`); redacción con **Gemini** (SDK `google-genai`) | Lo fija el spec (RF-015/RF-020). El ID de modelo y el proveedor de acceso a Haiku (API directa vs Bedrock) es TD-002. Modelo multimodal para imágenes: D-015. |

### Flujo principal (mensaje de usuario → respuesta IA)

1. `POST /chat/conversations/{id}/messages` con `client_message_id` (idempotencia RF-038).
2. Lambda `api`: valida límites (D-005), persiste el mensaje (confirmación antes de mostrarse como
   enviado — RNF-003), encola job en `ai-jobs`, responde **202**.
3. `worker-ai`: aplica debounce/agregación (D-020), clasifica con Haiku (`FAQ`/`CATALOGO`/`ASESOR`/
   `OTRO` — RF-016), según intención consulta Pinecone o HERALD, redacta con Gemini (o inicia
   handoff si no hay evidencia — RF-018), persiste la respuesta, registra `AIUsage`, y si hay
   handoff encola notificación Slack.
4. El frontend, que hace polling de mensajes nuevos, muestra la respuesta.

---

## 3. Esqueleto de API Gateway: rutas → Lambdas y servicios

**Los endpoints concretos NO están definidos aún** — esto es el mapa de superficies. Cada superficie
vive como un router de FastAPI dentro de la Lambda `api` (ver `backend/api/routers/`).

### HTTP API — rutas

| Ruta APIGW | Auth | Router FastAPI | Superficie (qué expondrá) | RFs |
|---|---|---|---|---|
| `$default` (cae en `/chat/*`) | Identidad VMC (**D-001**) o sesión anónima (**D-018**) | `chat` | Crear/cerrar conversación, enviar mensaje, listar mensajes (polling), solicitar handoff, presigned URL para subir imagen | RF-001..005, 008..014, 022, 040..042 |
| `/advisor/{proxy+}` | **JWT authorizer Cognito** (nativo de HTTP API) | `advisor` | Bandeja (por estado, no leídos), tomar conversación (atómica), ver hilo + contexto usuario (D-010), enviar mensaje, tickets, cerrar | RF-029..039, 012, 031 |
| `/dashboard/{proxy+}` | **JWT authorizer Cognito** | `dashboard` | Métricas operativas (D-013) | RF-047..049 |
| `GET /health` | pública | `main` | Healthcheck | — |

### Lambdas

| Lambda | Trigger | Responsabilidad | Notas |
|---|---|---|---|
| `api` | HTTP API (todas las rutas) | Todo lo síncrono: CRUD, validaciones, límites, presigned URLs, encolar. **No llama a la IA.** | FastAPI + Mangum, `lifespan="off"`. Timeout corto (~15 s). |
| `worker-ai` | SQS `ai-jobs` | Pipeline IA completo: debounce → Haiku → RAG/HERALD → Gemini → persistir → `AIUsage` → disparar handoff | Timeout largo (~60–120 s), memoria mayor. `batchItemFailures`. |
| `worker-notify` | SQS `notifications` | Notificación Slack de handoff/ticket (RF-028); futuro: correos, re-alertas (D-016) | Pequeña y aislada: si Slack cae, no afecta al pipeline IA. |
| `worker-maintenance` *(condicional)* | EventBridge Schedule | Autocierre por inactividad, expiración de sesión anónima | **Solo si D-003/D-018 lo requieren** — no crear hasta cerrarlas. |

### Colas SQS

| Cola | Consumidor | Reglas |
|---|---|---|
| `ai-jobs` (+ `ai-jobs-dlq`) | `worker-ai` | `visibility_timeout ≥ 6 × timeout del worker` (si no, SQS re-entrega mensajes en proceso y aparece "trabajo duplicado" que parece bug de lógica). `DelaySeconds` por mensaje puede servir para el debounce de D-020. |
| `notifications` (+ `notifications-dlq`) | `worker-notify` | maxReceiveCount bajo (3) → DLQ + alarma. |

### Resto de servicios AWS

- **DynamoDB** — 5 tablas (§4), `PAY_PER_REQUEST`, TTL habilitado.
- **S3** — bucket de imágenes: subida por presigned URL, lectura por presigned GET, lifecycle rule
  de retención (D-014), bloqueo de acceso público.
- **Cognito** — User Pool de asesores: invitación por correo (RF-006), rol único `ADVISOR` en el
  MVP (RF-007) pero con `role` en el modelo para crecer.
- **Secrets Manager** — `anthropic_api_key`, `gemini_api_key`, `pinecone_api_key`,
  `slack_webhook_url`, credenciales HERALD, secreto de integración VMC (D-001).
- **CloudWatch** — logs estructurados, métricas, alarmas (DLQ > 0, errores 5xx, latencia) — RNF-006.
- **EventBridge** — solo si D-003/D-018 exigen jobs programados.

### Integraciones externas (ninguna corre en AWS)

| Integración | Uso | Decisión que la bloquea |
|---|---|---|
| Anthropic API — Haiku `claude-haiku-4-5` | Clasificación de intención, orquestación de lectura | TD-002 (API directa vs Bedrock) |
| Gemini (`google-genai`) | Redacción de respuestas | modelo exacto por definir al implementar |
| Pinecone | RAG de conocimiento FAQ/VMC | carga de contenido inicial (proceso de ingesta no está en el spec — definir) |
| HERALD | Catálogo de vehículos en tiempo real | **D-011** (contrato) y **D-012** (fallback) |
| Slack | Webhook entrante para notificar handoffs | **D-016** (canal y formato) |
| VMC | Identidad del usuario autenticado + datos de solo lectura | **D-001** y **D-010** |

---

## 4. Modelo de datos — DynamoDB (5 tablas)

Modelo acordado: `subastin-conversations`, `subastin-messages`, `subastin-tickets`,
`subastin-advisors`, `subastin-ai-usage`. Sin tabla `users` (VMC es la fuente de identidad).
Imágenes en S3 (solo metadata en `Messages.attachment`). Eventos de auditoría como mensajes
`sender_type=SYSTEM` (`HANDOFF_REQUESTED`, `ADVISOR_ASSIGNED`, `BOT_DISABLED/ENABLED`,
`CONVERSATION_CLOSED`) — cubre RF-050 sin sexta tabla.

### Resumen de claves e índices

| Tabla | PK | SK | GSIs |
|---|---|---|---|
| `Conversations` | `conversation_id` | — | GSI1 `user_id`/`updated_at` (convs. de un usuario — RF-012) · GSI2 `status`/`last_message_at` (bandeja — RF-032) · GSI3 `assigned_advisor_id`/`updated_at` (casos de un CAM) |
| `Messages` | `conversation_id` | `created_at#message_id` | — (orden cronológico gratis por SK) |
| `Tickets` | `ticket_id` | — | GSI1 `conversation_id`/`created_at` · GSI2 `assigned_advisor_id`/`updated_at` · GSI3 `status`/`created_at` |
| `Advisors` | `advisor_id` | — | GSI `cognito_sub` (lookup desde el JWT) |
| `AIUsage` | `conversation_id` | `created_at#execution_id` | GSI `billing_month`/`created_at` (costos mensuales) |

### Revisión del modelo contra el spec — veredicto

El modelo **cumple** los patrones de acceso del MVP y no bloquea nada del "fuera de alcance". La
toma atómica (AC-005) se resuelve con `UpdateItem` condicional sobre `Conversations`
(`status = PENDING_ADVISOR AND attribute_not_exists(assigned_advisor_id)`) — no necesita nada extra
del modelo. Ajustes detectados (agregar al modelo antes de crear tablas):

1. **Falta `unread_count` en `Conversations`** — RF-032/035 piden contador de no leídos en la
   bandeja; se incrementa al persistir mensaje entrante y se resetea al abrir el asesor.
2. **Falta `wait_message_sent` (Boolean) en `Conversations`** — RF-027: el mensaje fijo de espera
   se envía máximo una vez por período pendiente; un flag es más barato que escanear mensajes.
3. **Falta `expires_at` (TTL) en `Messages`** — la retención (RF-053/D-014) aplica a conversaciones
   *e* imágenes *y* mensajes; `Conversations` ya lo tiene. En `AIUsage` probablemente NO va TTL
   (los datos de costo se quieren conservar) — confirmar al cerrar D-014.
4. **Idempotencia (RF-038/RNF-004) necesita un mecanismo, no solo el campo** — `client_message_id`
   existe pero la SK lleva `created_at` del servidor, así que un retry generaría otra SK y
   duplicaría. Patrón recomendado: `TransactWriteItems` con un item marcador
   (`PK=conversation_id, SK=CMID#<client_message_id>`, condición `attribute_not_exists`) + el
   mensaje real. Si la transacción falla por condición → duplicado, se responde el mensaje original.
5. **GSI2 de `Conversations` (PK=`status`)** — cardinalidad baja; con volumen MVP no es problema,
   pero la partición `CLOSED` crece sin límite. Mitigación barata: usar un atributo *sparse*
   (p. ej. `inbox_status` presente solo mientras no está `CLOSED`) para que el índice contenga solo
   lo operativo. Opcional; decidir al implementar la bandeja.
6. **`AIUsage` vs alcance** — "costos IA" está fuera del dashboard MVP (RF-049); la tabla se
   alimenta desde el día 1 (es barata y los datos no se pueden reconstruir), pero **no** se expone
   en la UI del MVP.
7. **GSIs se deciden ahora** — agregar un GSI después funciona, pero el backfill de datos
   existentes es migración manual; por eso los ajustes 1–5 deben cerrarse antes de la primera tabla
   en stage.
8. **D-017 (¿múltiples tickets por conversación?)** — el modelo ya lo soporta (Tickets GSI1 es
   1:N); la decisión solo restringe lógica de aplicación, no el modelo. ✔

---

## 5. Entornos y despliegue

### dev — 100% local (Docker + imágenes locales de AWS)

Sin cuenta AWS, sin credenciales reales. `docker-compose.yml` levanta:

| Servicio local | Imagen | Emula |
|---|---|---|
| `dynamodb` | `amazon/dynamodb-local` (imagen oficial de AWS) | DynamoDB |
| `localstack` | `localstack/localstack` (community, `SERVICES=sqs,s3`) | SQS + S3 (AWS no publica imagen oficial para estos; alternativa: elasticmq + MinIO) |

- La API corre como **uvicorn directo** (`uvicorn backend.api.main:app --reload`) — no se emula
  Lambda en dev; Mangum solo envuelve en AWS.
- Los workers corren como **script local** que consume de la cola de LocalStack
  (`python -m backend.workers.local_runner` — pendiente de implementar).
- Los `endpoint_url` locales se inyectan por `.env`; en AWS quedan `None` y boto3 resuelve solo.
- `cdk synth` valida la infra sin desplegar nada.

### stage y prod — CDK v2 (Python)

Un **stack por stage, mismo código**, parametrizado por contexto (`-c stage=...`). Config por stage
centralizada en `infra/config.py` (nombres con sufijo, memoria, log retention, alarmas, dominio).

```bash
# dependencias (una vez)
cd infra && pip install -r requirements.txt     # aws-cdk-lib, constructs, aws-cdk.aws-lambda-python-alpha
npm i -g aws-cdk                                # CLI

# una vez por cuenta+región (lo hace o autoriza el equipo AWS — ver §6)
cdk bootstrap aws://<account>/<region>

# ciclo
cdk synth  -c stage=stage      # validar template sin desplegar
cdk deploy -c stage=stage
cdk watch  -c stage=stage      # hotswap del código Lambda en ~3 s (solo cambios de código; si tocas infra hace deploy completo)
cdk deploy -c stage=prod
cdk destroy -c stage=stage
```

**Gotchas conocidos (no descubrirlos en producción):**

1. `PythonFunction` (del paquete alpha) bundlea dependencias **dentro de Docker** → se necesita
   Docker corriendo en la máquina para cualquier `cdk deploy`.
2. Si `requirements.txt` del backend supera **250 MB descomprimido** (pasa rápido con SDKs
   grandes), cambiar a `DockerImageFunction` con Dockerfile propio (sube el cold start,
   desaparece el límite) → TD-005.
3. `visibility_timeout ≥ 6 ×` timeout del worker (ver §3).
4. Los GSI de DynamoDB se deciden **antes** de crear tablas (backfill manual después).
5. En prod: `RemovalPolicy.RETAIN` + `deletion_protection` en tablas y bucket.

### Frontend

- Scaffold: `npx create-next-app@latest frontend` (TypeScript + Tailwind + App Router + ESLint,
  defaults actuales). Vacío por ahora.
- **Fuera del stack CDK**: se despliega en Vercel o Amplify (TD-003) apuntando al output `ApiUrl`
  del stack.
- Contendrá tres superficies: widget de chat embebible en VMC (mecánica de embed depende de
  **D-001**), app del asesor (login Cognito) y dashboard.

### Flujo de ramas y CI/CD (detalle en las skills `commit` y `ci-cd`)

- Repo: `https://github.com/rcoorahua/chatbot-ai-vmc`. Ramas `feature/*` / `fix/*` (≤ 2–3 días)
  → PR a **`develop`** (trunk de integración) → PR de release a **`main`** (protegida).
- **CI** (`.github/workflows/ci.yml`): ruff + pytest (con dynamodb-local/localstack como
  services) + `cdk synth` — corre en todo PR y push a develop/main, **sin credenciales AWS**.
- **CD** (`.github/workflows/deploy.yml`): develop → stage, main → prod (gate de reviewers), con
  OIDC. Maquetado y **apagado (`if: false`) hasta cerrar §6**.

**Estado de las protecciones** (configurado el 2026-08-24): default branch `develop`, borrado de
rama al mergear, environments `stage` y `prod` creados. La **protección de ramas del servidor no
está activa**: GitHub no la permite en repos privados con plan Free (403 `Upgrade to GitHub
Pro`), y tampoco los rulesets ni los required reviewers del environment `prod`. Sustituto local:
el hook versionado `.githooks/pre-push` bloquea pushes directos a `main`/`develop`
(`git config core.hooksPath .githooks` una vez por clon).

Al pasar a GitHub Pro (o mover el repo a una organización con plan Team), activar en el servidor:

```bash
export GITHUB_TOKEN=<token>          # solo en la terminal, nunca en un archivo
R=https://api.github.com/repos/rcoorahua/chatbot-ai-vmc
H=(-H "Authorization: Bearer $GITHUB_TOKEN" -H "Accept: application/vnd.github+json")

curl -s -X PUT "${H[@]}" $R/branches/main/protection -d '{
  "required_status_checks":{"strict":true,"contexts":["lint","test","synth"]},
  "enforce_admins":true,
  "required_pull_request_reviews":{"required_approving_review_count":0,"dismiss_stale_reviews":true},
  "restrictions":null,"allow_force_pushes":false,"allow_deletions":false,
  "required_conversation_resolution":true}'

curl -s -X PUT "${H[@]}" $R/branches/develop/protection -d '{
  "required_status_checks":{"strict":true,"contexts":["lint","test","synth"]},
  "enforce_admins":false,
  "required_pull_request_reviews":{"required_approving_review_count":0},
  "restrictions":null,"allow_force_pushes":false,"allow_deletions":false}'

# gate manual de prod (requiere Pro): reviewers en el environment
UID=$(curl -s "${H[@]}" https://api.github.com/users/rcoorahua | grep -m1 '"id"' | tr -dc 0-9)
curl -s -X PUT "${H[@]}" $R/environments/prod -d "{\"reviewers\":[{\"type\":\"User\",\"id\":$UID}]}"
```

`required_approving_review_count: 0` es deliberado: siendo un solo dev, GitHub no permite aprobar
el PR propio; el gate real es el CI en verde.

---

## 6. Qué solicitar al equipo de AWS (keys y accesos)

Checklist para la reunión con el equipo que administra la cuenta:

1. **Cuentas y región.** ¿Stage y prod en cuentas separadas (recomendado por AWS) o una sola cuenta
   con sufijos por stage? (→ TD-004). Confirmar región (¿`us-east-1`?). Necesitamos el/los
   **account ID**.
2. **CDK bootstrap** — una vez por cuenta+región (`cdk bootstrap aws://<account>/<region>`). Crea:
   bucket S3 de staging, repo ECR y **5 roles IAM** (`cdk-*`: deploy, file-publishing,
   image-publishing, lookup, cfn-exec). Opciones:
   - que el equipo AWS lo ejecute él mismo (lo usual cuando controlan IAM), o
   - que nos den permisos temporales de CloudFormation + IAM (`iam:CreateRole`,
     `iam:AttachRolePolicy`, etc.) para ejecutarlo nosotros.
   - Si la organización exige **permission boundaries**, el bootstrap debe hacerse con
     `--custom-permissions-boundary` / `--cloudformation-execution-policies` (política custom en
     vez de `AdministratorAccess` del default).
3. **Permiso de despliegue para desarrolladores** — solo se necesita
   `sts:AssumeRole` sobre `arn:aws:iam::*:role/cdk-*`. CDK asume esos roles; no hacen falta
   permisos amplios personales.
4. **Método de credenciales** — pedir **IAM Identity Center (SSO)** con perfil
   (`aws configure sso`) en vez de access keys estáticas. Si solo dan keys, que sean por
   desarrollador y rotables.
5. **Secrets Manager** — permiso para crear/leer los secretos listados en §3, o que el equipo los
   cree y nos pase los ARNs.
6. **Cognito** — permiso para crear User Pools (va dentro del stack CDK). Los correos de
   invitación del MVP salen con el email default de Cognito (suficiente para pocos asesores); si
   se quiere remitente propio → SES verificado (pedirlo solo si se decide).
7. **Dominio y certificado** — ¿habrá dominio custom para la API (`api.subastin...`)? Quién maneja
   Route53/DNS y ACM (→ TD-007). No bloquea el MVP (se puede usar la URL default de API Gateway).
8. **Bedrock** — preguntar si la cuenta tiene **Amazon Bedrock habilitado con acceso a modelos
   Claude**. Define TD-002 (Haiku vía Bedrock = facturación centralizada en AWS y sin API key
   externa; vía API Anthropic directa = features más recientes y mismo SDK en dev).
9. **Presupuesto/alertas** — pedir AWS Budgets o alarma de billing para stage y prod.

Referencias: [CDK bootstrapping](https://docs.aws.amazon.com/cdk/v2/guide/bootstrapping.html) ·
[cdk bootstrap CLI](https://docs.aws.amazon.com/cdk/v2/guide/ref-cli-cmd-bootstrap.html) ·
[Permissions](https://docs.aws.amazon.com/cdk/v2/guide/permissions.html) ·
[Permissions boundaries](https://docs.aws.amazon.com/cdk/v2/guide/customize-permissions-boundaries.html)

---

## 7. Estructura de directorios objetivo

Backend = **monolito modular** (misma filosofía que la v0: dependencias en una sola dirección,
repositories como único lugar que conoce claves de DynamoDB, integraciones hoja que no importan
dominio). La regla completa de capas está en `backend/__init__.py`. Mapeo desde la v0:
`conversaciones` → `conversations` (sigue siendo el corazón), `agente` → `agent` (expandido:
clasificador + redactor + RAG + usage), `subastin` → routers delgados en `api/`, `whatsapp` →
desaparece (fuera del MVP); los módulos nuevos existen porque el spec agregó tablas
(`tickets`, `advisors`) e integraciones (`catalog`, `notifications`, `images`).

```
chatbot-ai-vmc/
├── backend/                    # monolito modular (capas: entradas → dominio → integraciones → core)
│   ├── api/                    # ENTRADA HTTP: FastAPI + Mangum (main.py, lifespan="off")
│   │   └── routers/            #   chat.py (público) · advisor.py · dashboard.py (Cognito JWT)
│   ├── workers/                # ENTRADA SQS: ai_worker.py (compone el pipeline IA) · notify_worker.py
│   ├── conversations/          # DOMINIO corazón: Conversations+Messages (models/repository/service)
│   ├── tickets/                # DOMINIO: handoff + Tickets (puede importar conversations)
│   ├── advisors/               # DOMINIO hoja: Advisors + lookup cognito_sub
│   ├── agent/                  # INTEGRACIÓN IA: classifier (Haiku) · writer (Gemini) · rag (Pinecone)
│   │                           #   · prompts · usage (tabla AIUsage)
│   ├── catalog/                # INTEGRACIÓN: cliente HERALD (D-011/D-012)
│   ├── notifications/          # INTEGRACIÓN: Slack (D-016)
│   ├── images/                 # INTEGRACIÓN: S3 presigned + metadata (D-015)
│   ├── core/                   # config · clients AWS · auth (no importa a nadie)
│   └── requirements.txt        # deps que se bundlean en las Lambdas
├── infra/                      # CDK v2 Python
│   ├── app.py                  # entry: SubastinStack por stage (-c stage=...)
│   ├── cdk.json
│   ├── config.py               # configuración por stage (stage/prod)
│   ├── requirements.txt
│   └── stacks/
│       └── subastin_stack.py   # tablas, colas, lambdas, HTTP API, Cognito, S3, alarmas
├── frontend/                   # Next.js (App Router, TS, Tailwind) — vacío por ahora
├── tests/                      # pytest (smoke hoy; cada fase agrega los tests de sus AC)
├── .github/workflows/          # ci.yml (ruff·pytest·synth en PRs) · deploy.yml (CD maquetado, apagado hasta §6)
├── docker-compose.yml          # dev local: dynamodb-local + localstack (sqs, s3)
├── .claude/                    # skills (spec-driven, testing, commit, deploy, llm-cost-optimizer,
│                               #   rag-architect, prompt-governance, ci-cd, docker-dev,
│                               #   security-guidance, skill-auditor, write-a-skill) + hook de seguridad
├── pyproject.toml              # entorno local de dev (sync manual con backend/requirements.txt)
├── REQUERIMENTS.md             # spec del MVP en el repo (RF/RNF/RB/AC/D + modelo DynamoDB v1.0)
├── PLAN.md                     # este documento
├── CLAUDE.md                   # registro de decisiones (leer SIEMPRE antes de implementar)
└── README.md                   # overview + quickstart dev
```

El esqueleto de `backend/` e `infra/` existe con stubs y TODOs — **nada está implementado**; los
endpoints y constructs concretos se definen al arrancar las fases.

---

## 8. Fases de implementación

Cada fase deja algo verificable. Los bloqueos por decisión se marcan.

| Fase | Contenido | Bloqueada por |
|---|---|---|
| **F0** | Solicitudes al equipo AWS (§6), bootstrap, `cdk deploy` del esqueleto con `GET /health` en stage | §6 |
| **F1** | Dominio conversaciones/mensajes + chat público con polling (sin IA): crear conversación, enviar/listar mensajes, idempotencia, límites básicos | D-002 (máx. convs.), D-018 (sesión anónima), D-005 (guardrails) |
| **F2** | Pipeline IA mínimo: SQS + `worker-ai` con Haiku (clasificación) + Gemini (redacción), sin RAG; registro `AIUsage` | TD-002, D-020 (debounce), D-006 (triviales) |
| **F3** | RAG: ingesta a Pinecone + FAQ con fuentes (RF-019) + regla "no inventar → handoff" (RF-018) | proceso de ingesta por definir |
| **F4** | Catálogo HERALD | **D-011**, D-012 |
| **F5** | Handoff completo: tickets, correo de anónimo (RF-003), Slack, Cognito, rutas `/advisor` (bandeja, toma atómica, mensajes, cierre) | D-007, **D-008**, D-016, D-017, D-019, **D-010**, **D-001** |
| **F6** | Imágenes: presigned URLs, render en chat/asesor, interpretación IA | D-015 |
| **F7** | Dashboard + hardening: métricas, retención/TTL, auditoría QA, escenarios AC-001..009 end-to-end | D-013, D-014, D-003 |

Frontend en paralelo: widget (F1+), app asesor (F5), dashboard (F7).

---

## 9. Registro de decisiones

- **Técnicas cerradas:** T1–T9 en §2.
- **De negocio abiertas:** D-001…D-020 — responsables **Silvana + Julio**; detalle completo en
  [REQUERIMENTS.md](REQUERIMENTS.md) §6. Las de prioridad Alta que bloquean arquitectura/seguridad: **D-001** (identidad
  VMC), **D-005** (guardrails), **D-007** (IA OFF en handoff), **D-008** (taxonomía tickets),
  **D-010** (campos de usuario), **D-011** (contrato HERALD), **D-014** (retención), **D-017**
  (conversación↔ticket), D-002, D-003.
- **Técnicas abiertas (TD):** ver [CLAUDE.md](CLAUDE.md) — TD-001 (polling vs WebSocket), TD-002
  (Haiku directo vs Bedrock), TD-003 (Vercel vs Amplify), TD-004 (cuentas separadas), TD-005
  (PythonFunction vs DockerImageFunction), TD-007 (dominio custom). TD-006 quedó **cerrada**:
  la v0 se eliminó del repo (backup en `../chatbot-ai-vmc-v0-backup.zip`).

**La lista operativa de qué está abierto y la regla de "parar y avisar" viven en
[CLAUDE.md](CLAUDE.md), que se lee en cada sesión.**
