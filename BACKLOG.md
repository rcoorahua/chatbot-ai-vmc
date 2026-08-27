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

Estos siete tickets **no dependen de ninguna decisión abierta**. Es todo el trabajo disponible
ahora mismo, y alcanza para que dos personas avancen varios días en paralelo.

| Ticket | Qué es | Track |
|---|---|---|
| T-01 | Configuración y clientes AWS (`core`) | Fundación |
| T-02 | Modelos y repositorio de conversaciones y mensajes | Dominio |
| T-03 | Módulo de asesores completo | Dominio |
| T-04 | Repositorio de consumo de IA (`AIUsage`) | IA |
| T-10 | Estructura del frontend y componentes del chat | Frontend |
| T-11 | Pantalla de bandeja del asesor (sin conectar) | Frontend |
| T-30 | Cliente de Slack | Integraciones |

**T-01 es prerrequisito de casi todo**, así que conviene hacerlo primero y mergearlo rápido.

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

`[...]` = decisiones que hay que cerrar antes de empezar ese ticket.

---

## 3. Tickets

### Fundación

**T-01 · Configuración y clientes AWS**
Requerimientos: base de todo · Depende de: — · Bloqueado por: nada
Archivos: `backend/core/config.py`, `backend/core/aws.py`
Qué incluye: clase `Settings` con pydantic-settings leyendo las variables que ya define
`.env.example`; factorías de clientes boto3 (DynamoDB, SQS, S3) que pasan `endpoint_url` solo
cuando existe, para que el mismo código sirva en local y en AWS. Los límites y políticas se
exponen como configuración, nunca como constantes en la lógica (§1.1 del spec, RNF-007).
Criterio: un test verifica que sin `endpoint_url` el cliente apunta a AWS y con él a local.

### Dominio

**T-02 · Modelos y repositorio de conversaciones y mensajes**
Requerimientos: RF-008 · Depende de: T-01 · Bloqueado por: nada
Archivos: `backend/conversations/models.py`, `backend/conversations/repository.py`
Qué incluye: modelos Pydantic `Conversation` y `Message`; repositorio con las operaciones ya
validadas contra DynamoDB en `tests/test_dynamo_queries.py` — obtener por id, listar por usuario,
bandeja por estado, por asesor, guardar mensaje idempotente con item marcador, listar mensajes
cronológicamente y ventana de contexto.
**Ojo:** solo persistencia. Las reglas de negocio (cuántas conversaciones activas, cuándo cerrar)
son T-05 y están bloqueadas.
Criterio: los tests de consulta existentes pasan usando el repositorio en vez de boto3 directo.

**T-03 · Módulo de asesores**
Requerimientos: RF-006, RF-007 · Depende de: T-01 · Bloqueado por: nada
Archivos: `backend/advisors/*`
Qué incluye: modelo `Advisor`, repositorio (por id y por `cognito_sub`), y el servicio que
resuelve un asesor a partir de los claims del JWT y registra `last_login_at`. Rol único `ADVISOR`,
pero el campo `role` queda listo para crecer.
Criterio: dado un `cognito_sub`, el servicio devuelve el asesor y marca su último acceso.

**T-05 · Lógica de conversación**
Requerimientos: RF-009, RF-010, RF-011, RF-013, RF-014 · Depende de: T-02
**Bloqueado por: D-002** (máximo de conversaciones activas), **D-005** (guardrails),
**D-018** (duración de sesión anónima), D-003 (cierre y reapertura), D-004 (resumen)
Archivos: `backend/conversations/service.py`
Qué incluye: crear conversación respetando el máximo, transiciones de estado, límites de mensajes
y frecuencia, ventana de contexto para la IA, cierre.

**T-06 · Endpoints del chat público**
Requerimientos: RF-001..RF-005, RF-012 · Depende de: T-05
**Bloqueado por: D-001** (mecanismo de identidad VMC)
Archivos: `backend/api/routers/chat.py`, `backend/core/auth.py`
Qué incluye: crear conversación, enviar mensaje (responde 202 y encola), listar mensajes para el
sondeo del frontend, y la dependencia de identidad — que jamás confía en un `user_id` del
frontend (RNF-005).

**T-07 · Handoff y tickets**
Requerimientos: RF-003, RF-022..RF-028 · Depende de: T-05, T-03, T-30
**Bloqueado por: D-007** (cuánto dura la IA apagada), **D-008** (taxonomía), **D-017**
(relación conversación↔ticket), D-019 (anónimo sin correo), D-016 (formato Slack)
Archivos: `backend/tickets/*`
Qué incluye: criterios de derivación, creación del ticket, apagado de la IA, mensaje de espera
una sola vez, y encolado de la notificación a Slack.

**T-08 · Endpoints del asesor**
Requerimientos: RF-029..RF-039 · Depende de: T-07, T-03
**Bloqueado por: D-010** (qué campos del usuario ve el asesor) · Requiere Cognito desplegado
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

**T-20 · Clasificador de intención**
Requerimientos: RF-015, RF-016 · Depende de: T-04
**Bloqueado por: TD-002** (¿Haiku por la API de Anthropic o por Bedrock?) — se desbloquea
preguntándole al equipo de AWS si Bedrock está habilitado
Archivos: `backend/agent/classifier.py`, `backend/agent/prompts.py`
Criterio: un conjunto de mensajes de ejemplo se clasifica correctamente en FAQ, CATALOG, ADVISOR
u OTHER, con al menos 95% de acierto (skill `prompt-governance`).

**T-21 · Redactor de respuestas**
Requerimientos: RF-019, RF-020 · Depende de: T-20 · Bloqueado por: D-004 (resumen)
Archivos: `backend/agent/writer.py`

**T-22 · Recuperación en Pinecone**
Requerimientos: RF-017, RF-018 · Depende de: T-21
**Bloqueado por:** el proceso de ingesta de contenido, que **no está en el spec** — hay que
definir qué documentos entran, quién los cura y cómo se re-indexan
Archivos: `backend/agent/rag.py`

**T-23 · Catálogo HERALD**
Requerimientos: RF-044..RF-046 · Depende de: T-20
**Bloqueado por: D-011** (contrato de la API), D-012 (qué hacer si se cae)
Archivos: `backend/catalog/*`

**T-24 · Worker de IA**
Requerimientos: orquesta RF-015..RF-021 · Depende de: T-20, T-21, T-22
Bloqueado por: D-006 (mensajes triviales), D-020 (agrupar mensajes seguidos)
Archivos: `backend/workers/ai_worker.py`
Qué incluye: la composición del pipeline completo. Es el único sitio donde el dominio y las
integraciones se juntan (regla de capas en `backend/__init__.py`).

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

### Frontend

**T-10 · Estructura y componentes del chat**
Requerimientos: RF-001, RF-034, RF-036 · Depende de: — · Bloqueado por: nada
Archivos: `frontend/src/`
Qué incluye: layout, rutas, y los componentes del hilo de chat (burbujas por remitente, marca de
tiempo, campo de envío) trabajando **contra datos de prueba locales**. Conectarlo al backend
depende de T-06, pero construirlo no.

**T-11 · Pantalla de bandeja del asesor**
Requerimientos: RF-032, RF-035, RF-036 · Depende de: — · Bloqueado por: nada
Archivos: `frontend/src/`
Qué incluye: lista de conversaciones con estado, tiempo de espera y contador de no leídos, contra
datos de prueba. Los campos del usuario que se muestran en el detalle dependen de D-010.

**T-12 · Conexión del widget con el backend**
Requerimientos: RF-001, RF-037, RF-038 · Depende de: T-06, T-10
**Bloqueado por: D-001** (cómo se embebe y cómo llega la identidad)
Qué incluye: sondeo de mensajes nuevos, reintento local de mensajes fallidos sin persistirlos.

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
| **D-001** identidad VMC | T-06, T-12 — todo el chat autenticado y el embed del widget | **Máximo.** Sin esto no hay producto usable |
| **D-005** guardrails | T-05, T-40 — límites, y con ellos el chat funcional | Alto |
| **D-002** máx. conversaciones | T-05 | Alto — es una respuesta de una línea |
| **D-018** sesión anónima | T-05 | Alto — junto con D-002 y D-005 completan T-05 |
| **D-008** taxonomía de tickets | T-07 | Alto — y es la que más trabajo de negocio requiere |
| **D-007** duración de IA apagada | T-07 | Alto — respuesta corta |
| **D-017** conversación↔ticket | T-07 | Alto — respuesta corta |
| **D-010** campos del usuario | T-08, T-11 | Alto — necesita coordinación con Bruce |
| **D-011** contrato HERALD | T-23 | Alto — depende del equipo de HERALD |
| **TD-002** acceso a Haiku | T-20, T-21, T-24 | Alto — se resuelve con una pregunta al equipo AWS |
| D-015 imágenes | T-40 | Medio |
| D-013 métricas | T-50 | Medio |
| D-004 resumen · D-006 triviales · D-020 debounce | T-21, T-24 | Medio — optimizaciones, no bloquean lo esencial |
| D-016 Slack · D-019 anónimo sin correo · D-009 tags | T-07, T-30 | Bajo — ajustes de detalle |
| **D-014** retención | Nada de código; define el TTL antes de crear tablas en AWS | Alto para infraestructura |

**Tres respuestas cortas —D-002, D-007, D-017— desbloquean dos tickets grandes.** Vale la pena
pedirlas primero aunque no sean las más importantes: son las de mejor relación entre esfuerzo de
decisión y trabajo liberado.

---

## 6. Antes de escribir código en cualquier ticket

1. Verificar en [CLAUDE.md](CLAUDE.md) que sus decisiones sigan cerradas (esta lista se
   desactualiza; el registro vivo manda).
2. Escribir primero el criterio de aceptación como test (skill `spec-driven`).
3. Rama corta desde `develop`, pull request cuando el CI esté verde (skill `commit`).
