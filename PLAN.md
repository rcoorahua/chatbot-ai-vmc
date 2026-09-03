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
- **Usuarios:** anónimos (sin datos, sin historial persistente — RF-002/004; solo FAQ, sin
  handoff — D-002) y autenticados (identidad validada por VMC — RF-005; **D-001 cerrada**: JWT
  firmado por el servidor de VMC, ver el flujo de sesión en §2).
- **Automatización:** clasificación de intención (RF-015; **Gemini flash-lite** por TD-008, Haiku
  como plan B), FAQ con **RAG sobre
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
  widget/ (JS en VMC)    │                                                                        │
  + Next.js (asesor,     │   API Gateway HTTP API                                                 │
  dashboard)             │   ├── $default ──────────────► Lambda `api` (FastAPI + Mangum)         │
  ── fetch ────────────► │   ├── /advisor/{proxy+} ──┐    │  · verifica JWT de VMC, sesión (D-001)│
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

0. `POST /chat/sessions` con el JWT de identidad de VMC (o vacío = anónimo) → token de sesión de
   Subastín + la conversación del usuario (autenticado: siempre la misma, id determinista;
   anónimo: nueva por sesión). Es el único punto por el que entra identidad (D-001,
   `core/auth.py`). **Implementado.**
1. `POST /chat/conversations/{id}/messages` con `client_message_id` (idempotencia RF-038) y el
   token de sesión como Bearer. **Implementado.**
2. Lambda `api`: valida límites (configurables; valores provisionales hasta D-005), persiste el
   mensaje en una transacción con el marcador de idempotencia (RNF-003/004), encola un `AIJob`
   (`core/jobs.py`) en `ai-jobs`, responde **202**. Si la cola falla, el mensaje queda
   `QUEUE_FAILED`: durable, no perdido. **Implementado.**
3. `worker-ai` (**pendiente**, bloqueado por D-004/D-006/D-020): aplica debounce/agregación
   (D-020), clasifica (`agent.classifier`, `FAQ`/`CATALOG`/`ADVISOR`/`OTHER` — RF-016), según
   intención consulta Pinecone o HERALD, redacta (`agent.writer`, o inicia handoff si no hay
   evidencia — RF-018), persiste la respuesta, registra `AIUsage`, y si hay handoff encola
   notificación Slack. Anónimo + `ADVISOR` = texto fijo invitando a iniciar sesión (D-002).
4. El widget sondea mensajes nuevos (`GET …/messages?after=<message_key>`) y muestra la
   respuesta. **Implementado.**

---

## 3. Esqueleto de API Gateway: rutas → Lambdas y servicios

Los endpoints de `chat` están implementados (`backend/api/routers/chat.py`); `advisor` y
`dashboard` siguen como mapa de superficies. Cada superficie vive como un router de FastAPI dentro
de la Lambda `api` (ver `backend/api/routers/`).

### HTTP API — rutas

| Ruta APIGW | Auth | Router FastAPI | Superficie (qué expondrá) | RFs |
|---|---|---|---|---|
| `$default` (cae en `/chat/*`) | `POST /chat/sessions` verifica el JWT de VMC (D-001) y emite el token de sesión; el resto exige ese token como Bearer, atado a UNA conversación | `chat` | **Hecho:** sesión, conversación, enviar mensaje (202 + job), listar mensajes (polling con cursor). **Pendiente:** solicitar handoff, presigned URL para subir imagen | RF-001..005, 008..014, 022, 040..042 |
| `/advisor/{proxy+}` | **JWT authorizer Cognito** (nativo de HTTP API); la Lambda lee los claims del evento (`core/auth.py`). En local, `ADVISOR_DEV_AUTH=1` imita al authorizer (`api/dev_auth.py`) | `advisor` | **Hecho:** `GET /me` (auto-alta D-021), bandeja (`GET /conversations?status=&mine=`), detalle, hilo (últimos 20, `before`/`after`, consume no leídos), `POST …/take` (atómica), `POST …/messages` (idempotente, solo el asignado — D-022), `POST …/close` (cierre mínimo — D-023). **Hecho 2026-09-02 (tickets):** `GET /taxonomy` (⚠️ propuesta D-008), `GET /tickets?status=&mine=`, `GET /conversations/{id}/ticket` (lo crea si faltaba), `PATCH /tickets/{id}` (confirmar o corregir + datos mínimos), y el cierre acepta `resolution`. **Pendiente:** campos definitivos del usuario (D-010) | RF-006, 012, 023, 024, 029, 031..036, 038 |
| `/dashboard/{proxy+}` | **JWT authorizer Cognito** | `dashboard` | Métricas operativas (D-013) | RF-047..049 |
| `GET /health` | pública | `main` | Healthcheck | — |

### Lambdas

| Lambda | Trigger | Responsabilidad | Notas |
|---|---|---|---|
| `api` | HTTP API (todas las rutas) | Todo lo síncrono: CRUD, validaciones, límites, presigned URLs, encolar. **No llama a la IA.** | FastAPI + Mangum, `lifespan="off"`. Timeout corto (~15 s). |
| `worker-ai` | SQS `ai-jobs` | Pipeline IA completo: debounce → Haiku → RAG/HERALD → Gemini → persistir → `AIUsage` → disparar handoff | Timeout largo (~60–120 s), memoria mayor. `batchItemFailures`. |
| `worker-notify` | SQS `notifications` | Notificación Slack de handoff/ticket (RF-028); futuro: correos, re-alertas (D-016) | Pequeña y aislada: si Slack cae, no afecta al pipeline IA. |
| `worker-maintenance` *(condicional)* | EventBridge Schedule | Autocierre de tickets sin respuesta, re-encolado de mensajes `QUEUE_FAILED` | D-003 se cerró sin autocierre de conversación; queda solo si D-007 (ticket sin respuesta) lo exige o para el barrido de `QUEUE_FAILED`. |

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
  `slack_webhook_url`, credenciales HERALD, `vmc_identity_secret` (compartido con VMC, firma el
  JWT de identidad — D-001) y `session_signing_key` (propio, firma el token de sesión del widget).
- **CloudWatch** — logs estructurados, métricas, alarmas (DLQ > 0, errores 5xx, latencia) — RNF-006.
- **EventBridge** — solo si D-003/D-018 exigen jobs programados.

### Integraciones externas (ninguna corre en AWS)

| Integración | Uso | Decisión que la bloquea |
|---|---|---|
| Anthropic API — Haiku `claude-haiku-4-5` | Clasificación de intención, orquestación de lectura | TD-002 (API directa vs Bedrock) |
| Gemini (`google-genai`) | Redacción de respuestas | modelo exacto por definir al implementar |
| Pinecone | RAG de conocimiento FAQ/VMC — **implementado**: índice con embedding integrado (`multilingual-e5-large`), namespace `helpcenter`; ingesta desde el Centro de Ayuda con `scripts/helpcenter_fetch.py` + `helpcenter_upload.py` | nada: el proceso de ingesta quedó definido el 2026-08-27 (dos pasos, ver `data/helpcenter/README.md`) |
| HERALD | Catálogo de vehículos en tiempo real | **D-011** (contrato) y **D-012** (fallback) |
| Slack | Webhook entrante para notificar handoffs | **D-016** (canal y formato) |
| VMC | Identidad del usuario autenticado (JWT firmado por su servidor — D-001 cerrada, contrato en `widget/README.md`) + datos de solo lectura | **D-010** |

---

## 4. Modelo de datos — DynamoDB (5 tablas)

Modelo acordado: `subastin-conversations`, `subastin-messages`, `subastin-tickets`,
`subastin-advisors`, `subastin-ai-usage`. Sin tabla `users` (VMC es la fuente de identidad).
Imágenes en S3 (solo metadata en `Messages.attachment`). Eventos de auditoría como mensajes
`sender_type=SYSTEM` (`HANDOFF_REQUESTED`, `ADVISOR_ASSIGNED`, `TICKET_OPENED`, `TICKET_CLOSED`,
`BOT_DISABLED/ENABLED`, `CONVERSATION_CLOSED` — enum `SystemEvent` en
`conversations/models.py`) — cubre RF-050 sin sexta tabla y es lo que el widget dibuja como nota
de sistema en el hilo ("Ticket cerrado"), que es como D-003 hace visible el historial.

### Resumen de claves e índices

| Tabla | PK | SK | GSIs |
|---|---|---|---|
| `Conversations` | `conversation_id` | — | GSI1 `user_id`/`updated_at` (convs. de un usuario — RF-012) · GSI2 `status`/`last_message_at` (bandeja — RF-032) · GSI3 `assigned_advisor_id`/`updated_at` (casos de un CAM) |
| `Messages` | `conversation_id` | `created_at#message_id` | — (orden cronológico gratis por SK) |
| `Tickets` | `ticket_id` | — | GSI1 `conversation_id`/`created_at` · GSI2 `assigned_advisor_id`/`updated_at` · GSI3 `status`/`created_at` |
| `Advisors` | `advisor_id` | — | GSI `cognito_sub` (lookup desde el JWT) |
| `AIUsage` | `conversation_id` | `created_at#execution_id` | GSI `billing_month`/`created_at` (costos mensuales) |
| `RateLimits` ⚠️ **pendiente** | `IP#<hash>` / `USER#<id>` / `SESSION#<id>` | `YYYY-MM-DD` | — (solo lectura por clave completa) |

⚠️ **`RateLimits` está decidida (D-027, 31/08/2026) pero NO creada.** Es el tope diario de
ejecuciones de IA: contador con `ADD` atómico y **TTL a 48 h**, para que DynamoDB limpie solo y
no haga falta ningún proceso de purga. No lleva GSI porque siempre se lee por clave completa
(actor + día). Ver T-09 en BACKLOG.md; al crearla hay que tocar **infra y `local_setup.py`**,
que son espejo.

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
   1:N). Cerrada el 2026-08-27: varios tickets por conversación, máximo 5 activos por usuario;
   cerrar un ticket no cierra la conversación. ✔
9. **`status` en `Messages` (ajuste 6, implementado 2026-08-27)** — RF-008 exige un estado
   técnico por mensaje: `RECEIVED` (durable, pendiente del pipeline) → `PROCESSED`/`FAILED` por el
   worker; `QUEUE_FAILED` si la API no pudo encolar; `DELIVERED` para BOT/ADVISOR/SYSTEM.
10. **Id determinista para la conversación del autenticado** — `uuid5(user_id)` en
    `conversations/service.py`: hace atómica la regla "máximo 1" (D-002) con una creación
    condicional, sin consultar GSI1 antes de crear (dos pestañas a la vez no crean dos). GSI1
    sigue sirviendo para el historial que ve el asesor (RF-012).
11. **D-029 (2026-09-02): hilo + casos sin GSI nuevos** — `Conversations` gana `kind`
    (`THREAD`/`CASE`), `title`, `contact_name/email/phone`, `source_conversation_id` y
    `closed_by`; GSI1 (`user_id`/`updated_at`) lista el hilo y los casos del usuario y, con
    filtro, cuenta los casos abiertos para el tope. `Messages` gana el tipo `FORM_RESPONSE`
    (resumen legible en `content`, valores y transcripción del hilo en `metadata`). La
    conversación anónima y sus mensajes llevan `expires_at` (TTL, `ANONYMOUS_CONVERSATION_TTL_DAYS`).
    El caso se crea con sus tres primeros mensajes en una sola `TransactWriteItems`.

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

- **Widget del chat: `widget/subastin.js`** (implementado 2026-08-27) — JS plano sin build ni
  dependencias, Shadow DOM, se embebe en VMC con dos etiquetas `<script>` (contrato en
  `widget/README.md`). No vive en Next.js a propósito: lo que VMC carga es un archivo estático
  servible desde cualquier CDN, y `widget/test.html` lo prueba con solo `python -m http.server`.
  Hosting real: junto al frontend o en S3 + CloudFront (TD-003).
- **App del asesor y dashboard: `frontend/`** — scaffold `create-next-app` (TypeScript + Tailwind +
  App Router + ESLint), vacío por ahora. **Fuera del stack CDK**: se despliega en Vercel o Amplify
  (TD-003) apuntando al output `ApiUrl` del stack.

### Flujo de ramas y CI/CD (detalle en las skills `commit` y `ci-cd`)

- Repo: `https://github.com/rcoorahua/chatbot-ai-vmc`. Ramas `feature/*` / `fix/*` (≤ 2–3 días)
  → PR a **`develop`** (trunk de integración) → PR de release a **`main`** (protegida).
- **CI** (`.github/workflows/ci.yml`): ruff + pytest (con dynamodb-local/localstack como
  services) + `cdk synth` — corre en todo PR y push a develop/main, **sin credenciales AWS**.
- **CD** (`.github/workflows/deploy.yml`): develop → stage, main → prod (gate de reviewers), con
  OIDC. Maquetado y **apagado (`if: false`) hasta cerrar §6**.

**Estado de las protecciones** (activas desde 2026-08-25):

| Regla | `main` | `develop` |
|---|---|---|
| Pull request obligatorio | sí | sí |
| Checks requeridos para mergear | `lint`, `test`, `synth` | `lint`, `test`, `synth` |
| Rama al día con la base (`strict`) | sí | sí |
| Force push / borrado de rama | bloqueados | bloqueados |
| Aplica también a administradores | sí | no (permite hotfix) |

Además: default branch `develop`, borrado automático de la rama al mergear, y el environment
`prod` con **aprobación manual** (ningún despliegue a producción avanza sin revisión humana).
Complemento local: el hook versionado `.githooks/pre-push` bloquea pushes directos a
`main`/`develop` antes de salir de la máquina (`git config core.hooksPath .githooks` una vez por
clon).

**Condición que las habilita:** el repositorio es **público**. GitHub no ofrece protección de
ramas en repos privados con plan Free — se eligió publicidad sobre plan de pago para el MVP.
Consecuencia asumida: `REQUERIMENTS.md` (alcance funcional, reglas de negocio y decisiones
internas de VMC) es visible públicamente. Si el repo vuelve a privado, las protecciones se
desactivan solas y queda únicamente el hook local + el CI; la alternativa que conserva ambas
cosas es moverlo a una organización con plan Team (ver TD-004 y la nota de propiedad del código).


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
│   ├── agent/                  # INTEGRACIÓN IA: classifier · writer (Gemini, TD-008) · rag (Pinecone)
│   │                           #   · prompts · usage (tabla AIUsage)
│   ├── catalog/                # INTEGRACIÓN: cliente HERALD (D-011/D-012)
│   ├── notifications/          # INTEGRACIÓN: Slack (D-016)
│   ├── images/                 # INTEGRACIÓN: S3 presigned + metadata (D-015)
│   ├── core/                   # config · clients AWS · auth (identidad D-001) · clock · jobs (contrato SQS)
│   └── requirements.txt        # deps que se bundlean en las Lambdas
├── infra/                      # CDK v2 Python
│   ├── app.py                  # entry: SubastinStack por stage (-c stage=...)
│   ├── cdk.json
│   ├── config.py               # configuración por stage (stage/prod)
│   ├── requirements.txt
│   └── stacks/
│       └── subastin_stack.py   # tablas, colas, lambdas, HTTP API, Cognito, S3, alarmas
├── widget/                     # chat embebible: subastin.js (sin build) · test.html · README (contrato VMC)
├── data/helpcenter/            # conocimiento del bot: markdown descargado + chunks.json (no versionado)
├── scripts/                    # local_setup · seed_data · helpcenter_fetch · helpcenter_upload
├── frontend/                   # Next.js (App Router, TS, Tailwind) — app asesor y dashboard, vacío por ahora
├── tests/                      # pytest contra dynamodb-local/localstack reales; cada fase agrega los tests de sus AC
├── .github/workflows/          # ci.yml (ruff·pytest·synth en PRs) · deploy.yml (CD maquetado, apagado hasta §6)
├── docker-compose.yml          # dev local: dynamodb-local + localstack (sqs, s3)
├── .claude/                    # skills (spec-driven, testing, commit, deploy, llm-cost-optimizer,
│                               #   rag-architect, prompt-governance, ci-cd, docker-dev,
│                               #   security-guidance, skill-auditor, write-a-skill) + hook de seguridad
├── pyproject.toml              # entorno local de dev (sync manual con backend/requirements-*.txt)
├── REQUERIMENTS.md             # spec del MVP en el repo (RF/RNF/RB/AC/D + modelo DynamoDB v1.0)
├── PLAN.md                     # este documento
├── CLAUDE.md                   # registro de decisiones (leer SIEMPRE antes de implementar)
└── README.md                   # overview + quickstart dev
```

Implementado (2026-08-28): `core`, `conversations`, `advisors`, `api/routers/chat.py`,
`api/routers/advisor.py` (+ `api/dev_auth.py`), `agent` completo (clasificador, redactor, RAG,
triviales, AIUsage), `workers/ai_worker.py` (el bot responde; local con
`scripts/run_ai_worker.py`) y `widget/`. `tickets`, `catalog`, `notifications`, `images`,
`workers/notify_worker` y el router `dashboard` siguen como stubs; se definen al arrancar sus fases.

---

## 8. Fases de implementación

Cada fase deja algo verificable. Los bloqueos por decisión se marcan.

| Fase | Contenido | Bloqueada por |
|---|---|---|
| **F0** | Solicitudes al equipo AWS (§6), bootstrap, `cdk deploy` del esqueleto con `GET /health` en stage | §6 |
| **F1** | **Hecha 2026-08-27.** Dominio conversaciones/mensajes + chat público con polling (sin IA): sesión con identidad VMC, conversación única por usuario, enviar/listar mensajes, idempotencia, largo máximo configurable, widget embebible con página de prueba | Quedó provisional: D-005 (rate limit y límites por conversación), D-018 (sesión anónima 24 h) |
| **F2** | **Hecha 2026-08-28.** Pipeline IA completo en `workers/ai_worker.py`: debounce por DelaySeconds (D-020), triviales fijos (D-006), clasificación reglas→Gemini flash-lite (TD-008: Gemini también orquesta), RAG + redacción con el tier ANSWER de `core/llm.py` (2026-09-01: `gemini-3.6-flash`, respaldo `3.5-flash`), handoff mínimo (RF-022/025/026/027) y registro `AIUsage`. En local: `python -m scripts.run_ai_worker` | Slack espera D-016; ticket espera F5 |
| **F3** | RAG: ingesta y recuperación hechas 2026-08-27; **conectado al pipeline 2026-08-28**. `RAG_MIN_SCORE` calibrado el mismo día en `0.84` (CLAUDE.md "RAG") | — |
| **F4** | Catálogo HERALD | **D-011**, D-012 |
| **F5** | Handoff completo. **Adelantado 2026-08-27:** rutas `/advisor` de mensajería y módulo `advisors`. **2026-09-02:** handoff con formulario y casos (D-029) + **módulo `tickets` con la taxonomía del corpus como propuesta** (12 `problem_type`, categoría, prioridad, datos mínimos, reclasificación del asesor y cierre con resolución). **Pendiente:** Slack (D-016), campos de usuario (D-010) y el cierre formal de **D-008** por Silvana + Julio | D-016, **D-010**, **D-008** (abierta, con propuesta implementada) |
| **F6** | Imágenes: presigned URLs, render en chat/asesor, interpretación IA | D-015 |
| **F7** | Dashboard + hardening: métricas, retención/TTL, auditoría QA, escenarios AC-001..009 end-to-end | D-013, D-014 |

Frontend en paralelo: widget (F1+), app asesor (F5), dashboard (F7).

---

## 9. Registro de decisiones

- **Técnicas cerradas:** T1–T9 en §2.
- **De negocio cerradas (2026-08-27, Aaron):** D-001 (JWT firmado por el servidor de VMC), D-002
  (1 conversación; 5 tickets activos; anónimo solo FAQ), D-003 (conversación permanente; se
  cierran tickets, visibles en el hilo) y, por derivación, D-017 y D-019. D-018 provisional.
  Lado asesor (mismo día): D-021 (auto-alta al primer login), D-022 (responde solo quien tomó
  la conversación; sin ticket), D-023 (cierre mínimo sin ticket, provisional hasta F5).
- **De negocio cerradas (2026-08-28, Aaron):** D-004 (sin resumen: ventana de 20 mensajes de la
  última hora), D-005 (guardrails: 500 caracteres por mensaje —revisado el 31/08, antes 2000—,
  10 mensajes/min, imágenes 5 MB / 3 por mensaje / 20 por hora, sin tope acumulativo), D-006
  (triviales fijos sin llamada IA) y D-020
  (debounce de 6 s vía DelaySeconds de SQS) y D-007 (cerrada el mismo día, opción simple: la IA
  no se re-enciende sola; apagada hasta que un asesor tome y cierre el caso, sin expiración).
  Seguridad y tono del bot, mismo día: D-024 (guardrails: manipulación → fijo amable sin IA;
  datos de terceros → fijo de privacidad; verificación de la respuesta contra la evidencia en
  `agent/guardrails.py`), D-025 (un emoji máximo, sin markdown ni guiones largos) y D-026
  (golden set en `tests/golden/`, eval real manual con `scripts/eval_intents.py`, piso 95%).
  Detalle en [CLAUDE.md](CLAUDE.md).
- **De negocio cerrada (2026-09-02, Aaron): D-029 — casos y handoff con formulario.** Revisa
  D-002/D-003/D-017/D-019/D-023 tras estudiar Intercom y Zendesk (varias conversaciones por
  persona; el ticket es la conversación escalada). Autenticado: un hilo permanente con el bot
  (`kind=THREAD`) y hasta 5 casos abiertos (`kind=CASE`) que nacen del formulario de asesor
  (asunto + detalle); el hilo sigue con el bot encendido. Anónimo: una conversación por sesión,
  puede pedir asesor dejando nombre y correo (teléfono opcional; RF-003 vuelve a aplicar), se
  deriva en el sitio, con TTL y tope de handoffs por IP. Pedir asesor o "FAQ sin evidencia"
  ya no derivan solos: el bot ofrece la tarjeta (`HANDOFF_FORM`, mecanismo de D-028) y deriva
  `POST /chat/conversations/{id}/handoff`. Un caso o la anónima cerrados quedan `CLOSED` y de
  solo lectura; el hilo del autenticado vuelve al bot (D-023). Sin GSI nuevos. Detalle y
  código en [CLAUDE.md](CLAUDE.md).
- **De negocio abiertas:** D-006…D-016 y D-020 — responsables **Silvana + Julio**; detalle en
  [REQUERIMENTS.md](REQUERIMENTS.md) §6. Prioridad Alta que bloquea:
  **D-008** (taxonomía tickets), **D-010** (campos de usuario),
  **D-011** (contrato HERALD), **D-014** (retención).
- **Técnicas abiertas (TD):** ver [CLAUDE.md](CLAUDE.md) — TD-001 (polling vs WebSocket), TD-002
  (Haiku directo vs Bedrock), TD-003 (Vercel vs Amplify), TD-004 (cuentas separadas), TD-005
  (PythonFunction vs DockerImageFunction), TD-007 (dominio custom). TD-006 quedó **cerrada**:
  la v0 se eliminó del repo (backup en `../chatbot-ai-vmc-v0-backup.zip`).

**La lista operativa de qué está abierto y la regla de "parar y avisar" viven en
[CLAUDE.md](CLAUDE.md), que se lee en cada sesión.**
