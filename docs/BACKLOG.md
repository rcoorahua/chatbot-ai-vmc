# BACKLOG — desglose en tickets y dependencias

Este documento traduce los requerimientos de [REQUERIMENTS.md](REQUERIMENTS.md) a **unidades de
trabajo tomables**, con sus dependencias explícitas. Las fases de [PLAN.md](PLAN.md) §8 describen
el orden de entrega del producto; esto describe **qué puede coger cada quién sin bloquearse ni
pisarse con el otro**.

Cada ticket declara cuatro cosas:

- **Requerimientos** que cubre (trazabilidad con el spec).
- **Depende de** — otros tickets que deben estar hechos antes (dependencia técnica).
- **Bloqueado por** — decisiones de negocio (`D-xxx`) o técnicas (`TD-xxx`) sin cerrar. Si un
  ticket tiene esto, **no se empieza**: es la regla del proyecto (nada se asume).
- **Archivos** que toca — para que dos personas no editen lo mismo a la vez.

---

## 1. Qué se puede empezar hoy

**Hechos (2026-08-27):** T-01, T-02, T-05 (parcial), T-06, T-10, T-12 — es la F1 completa: chat
público con identidad VMC, persistencia y widget. También T-20 y T-21 (clasificador y redactor,
vía TD-008) y **T-22** (recuperación en Pinecone + ingesta del Centro de Ayuda).

Estos tickets **no dependen de ninguna decisión abierta** y son el trabajo disponible ahora mismo:

| Ticket | Qué es | Track |
|---|---|---|

| T-03 | Módulo de asesores completo | Dominio |
| T-04 | Repositorio de consumo de IA (`AIUsage`) | IA |
| T-11 | Pantalla de bandeja del asesor (sin conectar) | Frontend |
| T-30 | Cliente de Slack | Integraciones |

**T-09 hecho (01/09/2026).** D-027 revisada e implementada: anónimo 10/hora y 20/día
(sesión + hash de IP), autenticado el doble; apagado en dev (`AI_QUOTA_* = 0`), se enciende
por variables de entorno en stage/prod. Código en `agent/quota.py` + tabla `RateLimits`.

**T-24 hecho (2026-08-28):** D-004/D-006/D-020 se cerraron y el worker quedó conectado — el bot
responde (en local: `python -m scripts.run_ai_worker`). También T-04 (AIUsage). El siguiente
bloque grande es F5: tickets (D-008) y Slack (D-016).

---

## 2. Mapa de dependencias

```
                          T-01 core (config + clientes AWS)
                                      │
        ┌─────────────────────┬───────┴────────┬──────────────────┐
        ▼                     ▼                ▼                  ▼
   T-02 conversations    T-03 advisors    T-04 AIUsage      T-30 Slack
   (modelos + repo)      (completo)       (repo)            (cliente)
        │                     │                │                  │
        │                     │                ▼                  │
        │                     │           T-20 clasificador       │
        │                     │           [TD-002]                │
        │                     │                │                  │
        ▼                     │                ▼                  │
   T-05 service chat          │           T-21 redactor           │
   [D-002 D-005 D-018]        │                │                  │
        │                     │                ▼                  │
        ▼                     │           T-22 RAG Pinecone       │
   T-06 endpoints chat        │           [ingesta por definir]   │
   [D-001]                    │                                   │
        │                     │           T-23 catálogo HERALD    │
        │                     │           [D-011 D-012]           │
        └──────────┬──────────┘                                   │
                   ▼                                              │
            T-07 handoff + tickets ◄───────────────────────────────┘
            [D-007 D-008 D-017 D-019]
                   │
                   ▼
            T-08 endpoints asesor
            [D-010 · Cognito]
                   │
        ┌──────────┴──────────┐
        ▼                     ▼
   T-40 imágenes         T-50 dashboard
   [D-015]               [D-013]
```

`[...]` = decisiones que hay que cerrar antes de empezar ese ticket. **Ya hechos:** T-01, T-02,
T-05, T-06, T-10, T-12, T-20, T-21 (las decisiones que aparecen entre corchetes en esa rama —
D-001, D-002, D-018, TD-002 vía TD-008— se cerraron el 2026-08-27; D-005 quedó con valores
provisionales configurables).

---

## 3. Tickets

### Fundación

**T-01 · Configuración y clientes AWS** — ✅ hecho 2026-08-27
Requerimientos: base de todo · Depende de: — · Bloqueado por: nada
Archivos: `backend/core/config.py`, `backend/core/aws.py` (+ `clock.py`, `jobs.py`)
Qué incluye: clase `Settings` con pydantic-settings leyendo las variables que ya define
`.env.example`; factorías de clientes boto3 (DynamoDB, SQS, S3) que pasan `endpoint_url` solo
cuando existe, para que el mismo código sirva en local y en AWS. Los límites y políticas se
exponen como configuración, nunca como constantes en la lógica (§1.1 del spec, RNF-007).
Criterio: un test verifica que sin `endpoint_url` el cliente apunta a AWS y con él a local.

### Dominio

**T-02 · Modelos y repositorio de conversaciones y mensajes** — ✅ hecho 2026-08-27
(`tests/test_chat_conversations.py`)
Requerimientos: RF-008 · Depende de: T-01 · Bloqueado por: nada
Archivos: `backend/conversations/models.py`, `backend/conversations/repository.py`
Qué incluye: modelos Pydantic `Conversation` y `Message`; repositorio con las operaciones ya
validadas contra DynamoDB en `tests/test_dynamo_queries.py` — obtener por id, listar por usuario,
bandeja por estado, por asesor, guardar mensaje idempotente con item marcador, listar mensajes
cronológicamente y ventana de contexto.
**Ojo:** solo persistencia. Las reglas de negocio (cuántas conversaciones activas, cuándo cerrar)
son T-05 y están bloqueadas.
Criterio: los tests de consulta existentes pasan usando el repositorio en vez de boto3 directo.

**T-03 · Módulo de asesores** — ✅ hecho 2026-08-27 (`tests/test_advisor_api.py`)
Requerimientos: RF-006, RF-007 · Depende de: T-01 · Cerrada: D-021 (auto-alta al primer login)
Archivos: `backend/advisors/*`
Qué incluye: modelo `Advisor`, repositorio (por id y por `cognito_sub`), y el servicio que
resuelve un asesor a partir de los claims del JWT y registra `last_login_at`. Rol único `ADVISOR`,
pero el campo `role` queda listo para crecer.
Criterio: dado un `cognito_sub`, el servicio devuelve el asesor y marca su último acceso.

**T-05 · Lógica de conversación** — ✅ hecho 2026-08-28
Requerimientos: RF-009, RF-010, RF-011, RF-013, RF-014 · Depende de: T-02
Cerradas: D-002 (1 conversación), D-003 (conversación permanente; se cierran tickets), D-018
(provisional), **D-004** (ventana de 20 mensajes de la última hora, sin resumen) y **D-005**
(2000 caracteres, 10 mensajes/min → 429, límites de imagen). **Pendiente:** aplicar los límites
de imagen (F6) y el handoff, que trae la transición a `PENDING_ADVISOR` (T-07).
Archivos: `backend/conversations/service.py`

**T-06 · Endpoints del chat público** — ✅ hecho 2026-08-27 (`tests/test_chat_api.py`)
Requerimientos: RF-001..RF-005, RF-012 · Depende de: T-05
Cerrada: D-001 (JWT firmado por el servidor de VMC, contrato en `widget/README.md`)
Archivos: `backend/api/routers/chat.py`, `backend/core/auth.py`
Qué incluye: crear conversación, enviar mensaje (responde 202 y encola), listar mensajes para el
sondeo del frontend, y la dependencia de identidad — que jamás confía en un `user_id` del
frontend (RNF-005).

**T-07 · Handoff y tickets** — ✅ hecho 2026-09-02 (`tests/test_tickets_api.py`,
`tests/test_tickets_taxonomy.py`)
Requerimientos: RF-022..RF-028, RF-031 · Depende de: T-05, T-03
Hecho: handoff con formulario y casos (D-029), y el módulo `backend/tickets/*` completo —
taxonomía del corpus (12 `problem_type` con categoría, prioridad y datos mínimos), sugerencia
por reglas sin modelo, ciclo PENDING → IN_PROGRESS → CLOSED pegado a la conversación escalada,
reclasificación del asesor y cierre con resolución. El apagado de la IA, el mensaje de espera
una sola vez y las notas SYSTEM ya venían de F2/D-029.
⚠️ **La taxonomía es la PROPUESTA de Aaron: D-008 sigue abierta** y la cierran Silvana + Julio;
cerrarla es editar `backend/tickets/taxonomy.py`.
**Pendiente:** encolar la notificación a Slack (T-30 / **D-016**).

**T-08 · Endpoints del asesor** — ✅ mensajería hecha 2026-08-27 (`tests/test_advisor_api.py`)
Requerimientos: RF-029..RF-039 · Depende de: T-07, T-03
Hecho: bandeja, tomar (atómico), hilo con paginación, responder (idempotente), no leídos y cierre
mínimo sin ticket (D-021/D-022/D-023). **Pendiente:** el cierre real del ticket (T-07) y los
campos definitivos del usuario (**D-010** — hoy se exponen los que guarda la conversación).
En local el authorizer se imita con `ADVISOR_DEV_AUTH=1`; en AWS requiere Cognito desplegado
Archivos: `backend/api/routers/advisor.py`
Qué incluye: bandeja, tomar conversación (actualización condicional, ya probada), ver hilo con
contexto, responder, contador de no leídos, cerrar caso.

### IA

**T-04 · Repositorio de consumo de IA**
Requerimientos: base de la observabilidad de costos · Depende de: T-01 · Bloqueado por: nada
Archivos: `backend/agent/usage.py`
Qué incluye: registrar cada ejecución (tokens, costo, latencia, intención, si usó RAG, si derivó)
y la consulta de costo mensual por el índice de facturación. El costo se calcula con el precio
vigente al momento, como configuración con fecha — nunca un número suelto en el código.
Criterio: registrar dos ejecuciones y obtener el total del mes agregado por proveedor.

**T-20 · Clasificador de intención** — ✅ hecho 2026-08-27 (vía TD-008: Gemini también orquesta)
Requerimientos: RF-015, RF-016 · Depende de: T-04
TD-002 dejó de bloquear: el tier FAST lo atiende Gemini; Haiku es el plan B
Archivos: `backend/agent/classifier.py`, `backend/agent/prompts.py`
Criterio: un conjunto de mensajes de ejemplo se clasifica correctamente en FAQ, CATALOG, ADVISOR
u OTHER, con al menos 95% de acierto (skill `prompt-governance`).
**Golden set y guardrails (2026-08-28, D-024/D-025/D-026):** `tests/golden/intents.jsonl` (70+
casos), `backend/agent/guardrails.py` (entrada: manipulación y datos de terceros; salida:
cifras/enlaces fuera de la evidencia, fuga del prompt) y `scripts/eval_intents.py` (eval real
manual, piso 95%). Pendiente: correr la eval real con `GEMINI_API_KEY` y anotar el score base.

**T-21 · Redactor de respuestas** — ✅ hecho 2026-08-27 (D-004 cerrada el 28: ventana sin resumen)
Requerimientos: RF-019, RF-020 · Depende de: T-20
Archivos: `backend/agent/writer.py`

**T-22 · Recuperación en Pinecone** — ✅ hecho 2026-08-27 (`tests/test_agent_rag.py`,
`tests/test_helpcenter_ingest.py`)
Requerimientos: RF-017, RF-018, RF-019 · Depende de: T-21
Archivos: `backend/agent/rag.py`, `scripts/helpcenter_fetch.py`, `scripts/helpcenter_upload.py`
Ingesta definida (lo que estaba bloqueado): **entra el Centro de Ayuda público de VMC**, un chunk
por pregunta; lo cura quien revisa los `.md` que deja el fetch; se re-indexa corriendo los dos
scripts (`--replace` para un refresco completo). Detalle en `data/helpcenter/README.md`.
**Calibrado 28/08/2026:** `RAG_MIN_SCORE=0.84` (antes `0.75`, sin calibrar) contra el índice
real — margen angosto entre preguntas on-topic y off-topic, detalle en CLAUDE.md "RAG".
La conexión al pipeline (T-24) quedó hecha el 2026-08-28.

**T-23 · Catálogo HERALD**
Requerimientos: RF-044..RF-046 · Depende de: T-20
**Bloqueado por: D-011** (contrato de la API), D-012 (qué hacer si se cae)
Archivos: `backend/catalog/*`

**T-24 · Worker de IA** — ✅ hecho 2026-08-28 (`tests/test_ai_worker.py`, 19 casos)
Requerimientos: orquesta RF-015..RF-022, RF-025..RF-027 · Cerradas: D-006, D-020
Archivos: `backend/workers/ai_worker.py`, `backend/agent/trivial.py`, `backend/agent/usage.py`,
`scripts/run_ai_worker.py`
Qué incluyó: debounce por DelaySeconds + triviales + clasificación + RAG/redacción + handoff
mínimo + AIUsage. Es el único sitio donde dominio e integraciones se juntan (regla de capas).
**Pendiente:** Slack al derivar (T-30/D-016) y ticket al derivar (T-07/D-008).

### Integraciones

**T-30 · Cliente de Slack**
Requerimientos: RF-028 · Depende de: T-01 · Bloqueado por: nada para el cliente; **D-016** define
el canal y el formato del mensaje
Archivos: `backend/notifications/slack.py`, `backend/workers/notify_worker.py`
Qué incluye: el envío al webhook y el worker que consume la cola. El contenido exacto del mensaje
se ajusta al cerrar D-016 — se puede construir con una plantilla provisional y un test que
verifique el envío, no el texto.

**T-40 · Imágenes**
Requerimientos: RF-040..RF-043 · Depende de: T-02
**Bloqueado por: D-015** (tamaños, compresión y modelo multimodal), D-005 (límite de peso)
Archivos: `backend/images/*`

**T-09 · Tope de ejecuciones de IA** — ✅ hecho 01/09/2026 (D-027 revisada: 10/h y 20/d anónimo, doble autenticado, off en dev)
Requerimientos: RF-014, RNF-007, RNF-005 · Depende de: T-01, T-04 · Bloqueado por: nada
(**D-027 ya está cerrada**, 31/08/2026 — este ticket se puede empezar hoy)
Archivos: `infra/stacks/subastin_stack.py` **y** `scripts/local_setup.py` (tabla nueva, hay que
tocar los dos: el esquema está duplicado a propósito), `backend/core/config.py`,
`backend/conversations/service.py` o `backend/agent/usage.py`, `backend/api/routers/chat.py`,
`.env.example`, tests.

Por qué es prioritario: hoy el único freno para un anónimo es el de 10 mensajes/minuto de
D-005 — que deja pasar **14 400 llamadas de IA al día** desde una sola pestaña con un script.
Cada una cuesta dinero real de Gemini. Es el agujero de costo más grande que queda abierto.

Qué incluye:
- Tabla `RateLimits`: PK `IP#<hash>` / `USER#<id>` / `SESSION#<id>`, SK la fecha (`YYYY-MM-DD`),
  contador con `ADD` atómico y **TTL a 48 h** (que DynamoDB lo borre solo, sin proceso aparte).
- La IP sale de `requestContext.http.sourceIp` del evento de API Gateway HTTP API, que Mangum
  deja en `request.scope["aws.event"]` — el mismo camino que ya usa `core/auth.py` para los
  claims de Cognito. **No hace falta ninguna librería.** En local, `request.client.host`.
- Se guarda **hasheada** (HMAC con un secreto): la IP es dato personal y para contar da igual.
- Se cuenta la **ejecución de IA**, no el mensaje: los triviales y los guardrails no gastan
  cuota porque no llaman al modelo. `agent/usage.py` ya distingue esos casos.
- Topes de D-027: anónimo 10/día (IP y sesión, se agota la primera), autenticado 50/día por
  `user_id`, sin tope mientras atiende un asesor. `0 = ilimitado` y así queda en dev.
- Al agotarse: mensaje fijo del bot explicándolo (no un 500 ni silencio), y si el usuario es
  anónimo, invitarlo a iniciar sesión — que es justo lo que sube su cuota a 50.

Criterio de aceptación: un test agota la cuota de un anónimo y verifica que el mensaje 11 se
persiste pero **no** dispara llamada a IA; otro verifica que con `0` no hay tope; otro que un
mensaje trivial no consume cuota.

**Ojo al implementarlo:** CGNAT. Claro y Movistar sacan miles de móviles por la misma IP
pública, y una oficina entera también. El tope por IP va a golpear a usuarios legítimos que
comparten salida — por eso D-027 cuenta *también* por sesión y por eso el autenticado va por
`user_id` y nunca por IP.

### Frontend

**T-10 · Estructura y componentes del chat** — ✅ hecho 2026-08-27
Requerimientos: RF-001, RF-034, RF-036 · Depende de: — · Bloqueado por: nada
Archivos: `widget/subastin.js` (no `frontend/src/`: el widget es un script embebible sin build,
la app Next.js queda para el asesor y el dashboard)
Qué incluye: inicio, hilo (burbujas por remitente, hora por mensaje, notas de sistema al estilo
Intercom), centro de ayuda (estructura; el contenido lo entrega VMC), campo de envío.

**T-11 · Pantalla de bandeja del asesor**
Requerimientos: RF-032, RF-035, RF-036 · Depende de: — · Bloqueado por: nada
Archivos: `frontend/src/`
Qué incluye: lista de conversaciones con estado, tiempo de espera y contador de no leídos, contra
datos de prueba. Los campos del usuario que se muestran en el detalle dependen de D-010.

**T-12 · Conexión del widget con el backend** — ✅ hecho 2026-08-27
Requerimientos: RF-001, RF-037, RF-038 · Depende de: T-06, T-10
Cerrada: D-001. Incluye sesión (anónima/autenticada), sondeo de mensajes nuevos con cursor,
reintento local con el mismo `client_message_id`, y `widget/test.html` para probarlo.

**T-50 · Dashboard**
Requerimientos: RF-047..RF-049 · Depende de: T-08
**Bloqueado por: D-013** (qué métricas exactamente)

---

## 4. Reparto sugerido para dos desarrolladores

La división que menos conflictos genera es **por carpeta**, porque dos personas nunca editan el
mismo archivo:

| | Persona A — backend | Persona B — frontend e IA |
|---|---|---|
| Empieza con | **T-01** (y lo mergea rápido: lo necesita todo lo demás) | **T-10** (no depende de nada) |
| Sigue con | T-02 → T-03 | T-11 → T-04 → T-30 |
| Carpetas | `backend/core`, `backend/conversations`, `backend/advisors`, `backend/tickets` | `frontend/`, `backend/agent`, `backend/notifications` |

Si ambas personas son de backend, la división alternativa es **A: dominio** (`core`,
`conversations`, `advisors`, `tickets`) y **B: integraciones** (`agent`, `catalog`,
`notifications`, `images`). La regla de capas del proyecto ayuda: el dominio nunca importa
integraciones, así que las dos mitades se tocan en un solo punto — el worker de IA (T-24), que se
hace al final y entre los dos.

En ambos casos: ramas cortas y un pull request por ticket, siguiendo el flujo de la skill
`commit`. Un ticket que dure más de dos o tres días conviene partirlo.

---

## 5. Qué desbloquea cada decisión

Esta tabla ordena las decisiones por **cuánto trabajo liberan**, no por prioridad declarada. Sirve
para decidir en qué orden atacarlas con Silvana y Julio.

| Decisión | Desbloquea | Impacto |
|---|---|---|
| ~~**D-001** identidad VMC~~ | cerrada 2026-08-27 | — |
| ~~**D-005** guardrails~~ | **Cerrada 28/08/2026** — límites en `core/config.py` y en el stack | — |
| ~~**D-002** máx. conversaciones~~ | cerrada 2026-08-27 | — |
| ~~**D-018** sesión anónima~~ | provisional desde 2026-08-27 (confirmar) | — |
| **D-008** taxonomía de tickets | T-07 | Alto — y es la que más trabajo de negocio requiere |
| ~~**D-007** duración de IA apagada~~ | **Cerrada 28/08/2026** — apagada hasta cierre del asesor, sin expiración | — |
| ~~**D-017** conversación↔ticket~~ | cerrada 2026-08-27 | — |
| **D-010** campos del usuario | T-08, T-11 | Alto — necesita coordinación con Bruce |
| **D-011** contrato HERALD | T-23 | Alto — depende del equipo de HERALD |
| **TD-002** acceso a Haiku | T-20, T-21, T-24 | Alto — se resuelve con una pregunta al equipo AWS |
| D-015 imágenes | T-40 | Medio |
| D-013 métricas | T-50 | Medio |
| D-004 resumen · D-006 triviales · D-020 debounce | T-21, T-24 | Medio — optimizaciones, no bloquean lo esencial |
| D-016 Slack · D-009 tags (D-019 cerrada 2026-08-27) | T-07, T-30 | Bajo — ajustes de detalle |
| **D-014** retención | Nada de código; define el TTL antes de crear tablas en AWS | Alto para infraestructura |

**Lo que más trabajo libera ahora:** D-004 + D-006 + D-020 (con "no por ahora" basta) destraban
T-24 y con él la primera respuesta real del bot; D-008 destraba T-07 (handoff; D-007 ya cerró).

---

## 6. Antes de escribir código en cualquier ticket

1. Verificar en [CLAUDE.md](../CLAUDE.md) que sus decisiones sigan cerradas (esta lista se
   desactualiza; el registro vivo manda).
2. Escribir primero el criterio de aceptación como test (skill `spec-driven`).
3. Rama corta desde `develop`, pull request cuando el CI esté verde (skill `commit`).
