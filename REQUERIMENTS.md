# SUBASTÍN

Documentación del MVP de Subastín.

Este README consolida:

1. **Modelo DynamoDB para el MVP — Versión 1.0**
2. **Especificación de Requerimientos MVP — Spec-Driven, Versión 0.1**

---

# 1. Modelo DynamoDB para el MVP

**Versión:** 1.0  
**Modelo propuesto:** 5 tablas físicas

Incluye atributos, índices y justificación de cada parámetro.

El objetivo es mantener el MVP simple: cinco tablas DynamoDB bien delimitadas, con **S3** para imágenes, **Pinecone** para embeddings, **Cognito** para autenticación y **CloudWatch** para observabilidad técnica.

## 1.1 Principios del modelo

El modelo prioriza consultas reales del producto y evita sobrearquitectura. Cada tabla representa un dominio operativo claro: conversación, mensaje, ticket, asesor y uso de IA.

- DynamoDB no se usa como base relacional; las claves e índices se diseñan según los patrones de consulta.
- Las imágenes no se almacenan como binario en DynamoDB: se guardan en S3 y Dynamo conserva solo metadata y referencia.
- Los datos maestros del usuario siguen perteneciendo a VMC; Subastín almacena únicamente una copia mínima necesaria para operar el chat.
- Una conversación no equivale a un ticket. El ticket existe únicamente cuando hay intervención humana.
- CloudWatch conserva logs técnicos; `AIUsage` conserva datos funcionales y financieros necesarios para medir consumo, costo y rendimiento.
- Los valores de límites, TTL y políticas de cierre deben ser configurables y no quedar hardcodeados.

## 1.2 Resumen de tablas

| Tabla física | Responsabilidad | Volumen esperado | Comentario |
|---|---|---:|---|
| `subastin-conversations` | Estado y contexto de cada chat | Bajo/medio | Fuente para bandejas y estado actual |
| `subastin-messages` | Historial de mensajes | Alto | Principal tabla de crecimiento |
| `subastin-tickets` | Trabajo que requiere asesor | Medio | Se crea solo ante handoff humano |
| `subastin-advisors` | Usuarios internos/CAMs | Muy bajo | Sincronizado con Cognito |
| `subastin-ai-usage` | Ejecuciones, tokens y costos IA | Medio/alto | Permite medir Haiku/Gemini por conversación y mes |

---

## 1.3 Tabla 1 — Conversations

Guarda el estado actual de cada conversación. Es la tabla principal para construir la bandeja del asesor y resolver rápidamente qué está ocurriendo en un chat.

| Atributo | Tipo | Oblig. | Uso | Justificación |
|---|---|---|---|---|
| `conversation_id` | String/UUID | Sí | PK de la conversación | Identificador estable y único; permite acceder directamente al chat sin depender de datos externos |
| `user_id` | String | No | ID VMC del usuario autenticado | Permite recuperar historial de un usuario autenticado. Es nulo en chats anónimos |
| `user_type` | String | Sí | `AUTHENTICATED / ANONYMOUS` | Determina reglas de historial, identificación y handoff |
| `user_name` | String | No | Nombre visible del usuario | Evita consultar VMC para cada render de bandeja y permite mostrar el nombre al asesor |
| `user_email` | String | No | Correo disponible para contacto | En anónimos se solicita solo al derivar; en autenticados puede venir de VMC si se aprueba |
| `user_company` | String | No | Empresa asociada, si aplica | Puede ser útil para contexto del asesor sin hacer una llamada extra a VMC |
| `status` | String | Sí | `BOT_ATTENDING / PENDING_ADVISOR / IN_ATTENTION / CLOSED` | Es la base de la bandeja y del ciclo de vida de la conversación |
| `channel` | String | Sí | Canal de origen; MVP: `WEB` | Aunque hoy solo sea WEB, deja preparado el modelo para nuevos canales sin migración |
| `assigned_advisor_id` | String | No | CAM que tomó la conversación | Permite saber quién atiende el chat y construir la vista “mis conversaciones” |
| `bot_enabled` | Boolean | Sí | Indica si la IA puede responder | Evita inferir el estado del bot a partir de múltiples eventos; facilita handoff seguro |
| `summary` | String | No | Resumen acumulado para contexto IA | Reduce tokens si la conversación supera la ventana reciente |
| `summary_updated_at` | String ISO-8601 | No | Última actualización del resumen | Permite saber si el resumen está desactualizado y cuándo regenerarlo |
| `message_count` | Number | Sí | Cantidad total de mensajes | Sirve para guardrails, métricas y decisiones de resumen |
| `last_message_preview` | String | No | Preview corto del último mensaje | Evita consultar Messages solo para dibujar la bandeja |
| `last_message_at` | String ISO-8601 | Sí | Timestamp del último mensaje | Permite ordenar la bandeja por actividad/espera |
| `handoff_requested_at` | String ISO-8601 | No | Momento en que se pidió asesor | Permite calcular tiempo de espera y SLA |
| `handoff_reason` | String | No | Motivo del handoff | Explica por qué IA derivó y sirve para análisis posterior |
| `created_at` | String ISO-8601 | Sí | Fecha de creación | Auditoría y métricas |
| `updated_at` | String ISO-8601 | Sí | Última actualización del registro | Soporta ordenamiento y control de cambios |
| `closed_at` | String ISO-8601 | No | Fecha de cierre | Necesario para métricas de duración y retención |
| `expires_at` | Number epoch | No | TTL de DynamoDB | Permite borrar automáticamente datos cuando se defina la política de retención |

### Clave principal

```text
PK = conversation_id
```

### Índices recomendados

- **GSI1 — por usuario:** `PK=user_id`, `SK=updated_at`. Recupera conversaciones de un usuario autenticado sin hacer scans.
- **GSI2 — por estado:** `PK=status`, `SK=last_message_at`. Construye bandejas como `PENDING_ADVISOR` ordenadas por tiempo.
- **GSI3 — por asesor:** `PK=assigned_advisor_id`, `SK=updated_at`. Permite mostrar las conversaciones que está atendiendo un CAM.

### Notas de diseño

- No se recomienda guardar aquí datos sensibles completos. VMC sigue siendo la fuente de verdad.
- `last_message_preview` y `message_count` son datos desnormalizados deliberadamente para evitar consultas adicionales en cada carga de bandeja.
- `expires_at` solo se activa cuando Silvana + Julio definan la política final de retención.

---

## 1.4 Tabla 2 — Messages

Guarda el historial completo del chat. Esta será la tabla de mayor crecimiento y debe optimizarse para la consulta más común: traer mensajes de una conversación en orden.

| Atributo | Tipo | Oblig. | Uso | Justificación |
|---|---|---|---|---|
| `conversation_id` | String | Sí | PK | Agrupa todos los mensajes de una conversación en la misma partición |
| `message_key` | String | Sí | SK = `timestamp#message_id` | Mantiene orden cronológico y evita colisiones si dos mensajes llegan casi al mismo tiempo |
| `message_id` | String/UUID | Sí | ID único del mensaje | Referencia estable para auditoría, reintentos o futuras respuestas a mensajes |
| `sender_type` | String | Sí | `USER / BOT / ADVISOR / SYSTEM` | Permite renderizar correctamente el hilo y distinguir origen |
| `sender_id` | String | No | ID del usuario o asesor | Atribuye la acción a una identidad cuando existe |
| `message_type` | String | Sí | `TEXT / IMAGE / SYSTEM` | Permite tratar contenido y eventos del sistema de forma explícita |
| `content` | String | No | Contenido textual | Es nulo cuando el mensaje solo representa una imagen/evento |
| `client_message_id` | String | No | ID creado en frontend | Permite idempotencia en retries y evita duplicar un mensaje |
| `attachment` | Map | No | Metadata de imagen en S3 | Evita crear otra tabla en el MVP; el binario permanece fuera de DynamoDB |
| `created_at` | String ISO-8601 | Sí | Timestamp | Necesario para orden, auditoría y UI |
| `metadata` | Map | No | Datos adicionales | Permite extender eventos sin cambiar el esquema de la tabla |

### Clave principal

```text
PK = conversation_id
SK = created_at#message_id
```

### Notas de diseño

- No hace falta un GSI por fecha global para el MVP; los accesos normales parten de `conversation_id`.
- Los eventos funcionales de auditoría ligados al chat pueden representarse como `sender_type=SYSTEM` y `message_type=SYSTEM` para evitar una sexta tabla.
- Las imágenes se guardan en S3. `attachment` almacena `s3_key`, `mime_type`, `size_bytes`, `width` y `height`.
- Un mensaje fallido antes de confirmación no se persiste. El frontend lo mantiene temporalmente y reintenta con el mismo `client_message_id`.

---

## 1.5 Tabla 3 — Tickets

Representa trabajo que requiere atención humana. Se crea únicamente cuando una conversación necesita handoff; por ello conversación y ticket no son la misma entidad.

| Atributo | Tipo | Oblig. | Uso | Justificación |
|---|---|---|---|---|
| `ticket_id` | String/UUID | Sí | PK | Identificador único del trabajo humano |
| `conversation_id` | String | Sí | Conversación origen | Vincula el ticket con todo el contexto conversacional |
| `user_id` | String | No | ID VMC del usuario | Facilita filtros y auditoría cuando el usuario está autenticado |
| `user_email` | String | No | Correo de contacto | Necesario para usuarios anónimos si negocio decide exigirlo en handoff |
| `status` | String | Sí | `PENDING / IN_PROGRESS / CLOSED` | Representa el ciclo de atención humana, separado del estado de conversación |
| `assigned_advisor_id` | String | No | CAM responsable | Permite asignación y construcción de bandejas por asesor |
| `problem_type` | String | No | Tipo de problema | Se definirá con Silvana + Julio; habilita routing y métricas |
| `category` | String | No | Categoría de negocio | Permite clasificación más estable si se necesita separar categoría de `problem_type` |
| `tags` | List<String> | No | Tags complementarios | Soporta múltiples etiquetas sin crear otra tabla mientras el catálogo sea pequeño |
| `priority` | String | No | Prioridad del ticket | Permite ordenar o escalar casos cuando se defina la regla |
| `description` | String | No | Resumen del problema | Da contexto rápido al asesor sin releer todo el hilo |
| `required_data` | Map | No | Datos recolectados por tipo de ticket | Evita hardcodear columnas como `auction_id` o `vehicle_id` antes de cerrar la taxonomía |
| `handoff_reason` | String | Sí | Motivo de derivación | Permite entender por qué el bot no resolvió el caso |
| `created_at` | String ISO-8601 | Sí | Fecha de creación | Auditoría y métricas de volumen |
| `assigned_at` | String ISO-8601 | No | Fecha de toma | Permite calcular tiempo de espera |
| `updated_at` | String ISO-8601 | Sí | Último cambio | Ordenamiento y control de actividad |
| `closed_at` | String ISO-8601 | No | Fecha de cierre | Permite medir tiempo total de resolución |
| `closed_by` | String | No | Asesor que cerró | Auditoría |

### Clave principal

```text
PK = ticket_id
```

### Índices recomendados

- **GSI1 — por conversación:** `PK=conversation_id`, `SK=created_at`. Permite recuperar todos los tickets relacionados con un chat.
- **GSI2 — por asesor:** `PK=assigned_advisor_id`, `SK=updated_at`. Construye la bandeja de tickets de un CAM.
- **GSI3 — por estado:** `PK=status`, `SK=created_at`. Permite listar pendientes/en atención/cerrados sin scans.

### Notas de diseño

- `problem_type`, `category`, `tags` y `required_data` deben cerrarse con Silvana + Julio antes de considerarse obligatorios.
- `required_data` como Map permite capturar distintos campos por tipo de problema sin alterar la tabla en cada cambio de negocio.
- Si a futuro el volumen de tags o reglas crece, tags puede separarse en su propio catálogo; no es necesario para el MVP.

---

## 1.6 Tabla 4 — Advisors

Guarda la información mínima de los CAMs/asesores que trabajan dentro de Subastín. Cognito autentica; esta tabla contiene la información operativa que necesita la aplicación.

| Atributo | Tipo | Oblig. | Uso | Justificación |
|---|---|---|---|---|
| `advisor_id` | String/UUID | Sí | PK | Identificador interno estable del CAM |
| `cognito_sub` | String | Sí | ID del usuario en Cognito | Es el identificador confiable recibido después del login |
| `name` | String | Sí | Nombre visible | Se usa en asignaciones, bandeja y auditoría |
| `email` | String | Sí | Correo corporativo | Necesario para invitación, identificación y soporte |
| `role` | String | Sí | MVP: `ADVISOR` | Aunque solo exista un rol hoy, evita migrar el esquema cuando aparezcan `ADMIN/SUPERVISOR` |
| `status` | String | Sí | `INVITED / ACTIVE / DISABLED` | Permite deshabilitar acceso sin borrar historial |
| `created_at` | String ISO-8601 | Sí | Creación | Auditoría |
| `updated_at` | String ISO-8601 | Sí | Última actualización | Control de cambios |
| `last_login_at` | String ISO-8601 | No | Último acceso | Útil para operación y diagnóstico de cuentas |

### Clave principal

```text
PK = advisor_id
```

### Índices recomendados

- **GSI1 — por Cognito:** `PK=cognito_sub`. Permite resolver rápidamente el `advisor_id` interno a partir del token de Cognito.

### Notas de diseño

- Cognito sigue siendo la fuente de autenticación; no se almacenan contraseñas en DynamoDB.
- `status` evita borrar usuarios históricos y conserva integridad de tickets/mensajes atendidos.
- `role` se mantiene desde el inicio por compatibilidad futura, aunque el MVP solo utilice `ADVISOR`.

---

## 1.7 Tabla 5 — AIUsage

Registra cada ejecución de IA. Es necesaria para separar el costo de Haiku —lectura/orquestación— del costo de Gemini —escritura— y para medir tokens, latencia, fallos y handoffs.

| Atributo | Tipo | Oblig. | Uso | Justificación |
|---|---|---|---|---|
| `conversation_id` | String | Sí | PK | Agrupa el consumo IA por conversación y facilita trazabilidad de costo |
| `execution_key` | String | Sí | SK = `timestamp#execution_id` | Ordena llamadas y evita colisiones |
| `execution_id` | String/UUID | Sí | ID único | Referencia individual de la ejecución |
| `message_id` | String | No | Mensaje que disparó la llamada | Permite seguir el flujo mensaje → clasificación/respuesta |
| `execution_type` | String | Sí | `CLASSIFICATION / RESPONSE / SUMMARY / IMAGE_ANALYSIS` | Distingue lectura/orquestación de escritura y otros trabajos |
| `provider` | String | Sí | `ANTHROPIC / GOOGLE` | Permite separar costos por proveedor |
| `model` | String | Sí | Haiku / Gemini, etc. | Necesario porque precio y comportamiento cambian por modelo |
| `intent` | String | No | `FAQ / CATALOG / ADVISOR / OTHER` | Permite analizar distribución de consultas |
| `input_tokens` | Number | Sí | Tokens de entrada | Dato base del costo real |
| `output_tokens` | Number | Sí | Tokens de salida | Dato base del costo real |
| `cached_tokens` | Number | No | Tokens servidos por cache | Permite medir si prompt caching está reduciendo costos |
| `estimated_cost_usd` | Number | Sí | Costo calculado de la llamada | Permite dashboard financiero sin recalcular todo cada vez |
| `latency_ms` | Number | Sí | Latencia de la ejecución | Sirve para validar objetivo de respuesta y detectar degradación |
| `status` | String | Sí | `SUCCESS / ERROR / TIMEOUT` | Permite medir confiabilidad y tasa de error |
| `error_code` | String | No | Código o tipo de fallo | Ayuda a agrupar errores sin depender solo de logs técnicos |
| `rag_used` | Boolean | Sí | Indica uso de Pinecone/RAG | Separa respuestas RAG de otras rutas |
| `rag_results_count` | Number | No | Cantidad de chunks | Permite analizar recuperación y fallbacks |
| `handoff_triggered` | Boolean | Sí | Si terminó en asesor | Sirve para medir tasa de automatización/handoff |
| `billing_month` | String YYYY-MM | Sí | Mes contable | Simplifica consultas de costo mensual mediante GSI |
| `created_at` | String ISO-8601 | Sí | Timestamp | Auditoría y orden temporal |

### Clave principal

```text
PK = conversation_id
SK = created_at#execution_id
```

### Índices recomendados

- **GSI1 — por mes:** `PK=billing_month`, `SK=created_at`. Permite calcular consumo y costo mensual sin escanear toda la tabla.

### Notas de diseño

- CloudWatch conserva logs técnicos; `AIUsage` conserva métricas estructuradas que alimentan reportes y costos.
- `estimated_cost_usd` debe calcularse con el precio vigente del modelo al momento de la ejecución; conviene guardar el valor ya calculado.
- `execution_type` permite demostrar que Haiku y Gemini cumplen funciones distintas y medir sus costos por separado.

---

## 1.8 Por qué cinco tablas y no más

- **Users** no se separa por ahora porque VMC es la fuente de verdad. Conversations guarda una copia mínima de identidad necesaria para operar.
- **Attachments** no se separa porque el MVP solo maneja imágenes y la metadata cabe en el mensaje; el archivo real ya vive en S3.
- **AuditEvents** no se separa porque los eventos de conversación pueden registrarse como mensajes `SYSTEM` y los logs técnicos permanecen en CloudWatch.
- **Tags** no se separa mientras el catálogo sea pequeño y todavía esté pendiente de definición; puede guardarse como lista dentro de Tickets.
- **DailyMetrics** no es necesaria como fuente de verdad en el MVP; se puede calcular/agregar posteriormente desde Conversations, Tickets y AIUsage.

## 1.9 Decisiones que todavía afectan el esquema

| Decisión | Impacto en tablas | Estado |
|---|---|---|
| Cantidad de conversaciones activas | No cambia el esquema; cambia regla/índice de consulta | Silvana + Julio |
| Cierre y retención | Define `closed_at` y activación de `expires_at`/TTL | Silvana + Julio |
| Taxonomía de tickets | Define `problem_type`, `category`, `tags` y `required_data` | Silvana + Julio |
| Campos VMC/JWT | Define qué `user_*` se copia en Conversations | Silvana + Julio + Bruce |
| Procesamiento de imágenes | Define metadata adicional en `attachment` y límites | Silvana + Julio |
| Métricas del dashboard | Puede requerir GSIs o agregados adicionales, no necesariamente nuevas tablas | Silvana + Julio |

## 1.10 Recomendación de nombres físicos

```text
subastin-conversations
subastin-messages
subastin-tickets
subastin-advisors
subastin-ai-usage
```

---

# 2. Especificación de Requerimientos MVP

**Enfoque:** Spec-Driven  
**Versión:** 0.1  
**Estado:** Borrador de alcance funcional posterior al discovery  
**Fecha:** 21/08/2026  
**Decisiones abiertas:** identificadas como `D-XXX`

> **Principio del documento:** ningún punto pendiente se trata como supuesto cerrado. Los requerimientos RF representan comportamiento acordado; las decisiones D representan aspectos que deben cerrarse antes o durante la implementación.

---

## 2.1 Objetivo y alcance

Subastín será la plataforma propia de atención para reemplazar Intercom en el alcance del MVP. El producto centraliza el chat web de VMC, automatiza consultas frecuentes y de catálogo, y deriva a atención humana cuando la consulta no debe o no puede ser resuelta automáticamente.

- Canal conversacional del MVP: chat web integrado en VMC.
- Usuarios: autenticados y anónimos.
- Automatización: clasificación de intención, FAQ/RAG, catálogo HERALD y handoff a asesor.
- Atención humana: bandeja de conversaciones, toma de casos, respuesta, imágenes, auditoría y cierre.
- Operación: dashboard básico para CSMs/asesores.
- WhatsApp/Kapso: canal separado del chat web; no existe timeline omnicanal en el MVP.
- Datos de VMC: solo lectura. No se permite modificar datos del usuario desde Subastín.

### 2.1.1 Actores

| Actor | Descripción | Acceso MVP |
|---|---|---|
| Usuario anónimo | Persona que usa el chat sin sesión iniciada | FAQ, catálogo y derivación; sin historial persistente |
| Usuario autenticado | Usuario identificado por VMC | Chat, personalización e historial asociado a identidad |
| Asesor / CSM | Usuario interno que atiende handoffs y tickets | Aplicación de atención y dashboard operativo |
| Servicios IA | Haiku para lectura/orquestación y Gemini para redacción automática | Backend; sin acceso directo de usuario |
| HERALD | API externa/independiente para catálogo de vehículos | Integración desde backend |

---

# 3. Requerimientos funcionales (RF)

## 3.1 Acceso, identidad y sesión

| ID | Requerimiento funcional | Criterio / comportamiento esperado | Estado |
|---|---|---|---|
| RF-001 | Chat web para usuarios autenticados y anónimos | El widget/chat deberá poder abrirse sin exigir login. El usuario autenticado deberá quedar asociado a su identidad VMC | Acordado |
| RF-002 | El usuario anónimo inicia sin entregar datos | No se solicitará DNI, teléfono ni correo para iniciar una consulta automática | Acordado |
| RF-003 | Correo obligatorio únicamente al derivar un usuario anónimo | Cuando un usuario anónimo requiera atención humana, el flujo deberá solicitar correo antes de completar el handoff/ticket | Acordado |
| RF-004 | Sin historial persistente para usuarios anónimos | Un usuario no autenticado no recuperará conversaciones anteriores entre sesiones o dispositivos | Acordado |
| RF-005 | Identificación funcional del usuario autenticado | Subastín deberá recibir una identidad validada desde VMC para asociar usuario, conversaciones y mostrar saludo por nombre. El mecanismo técnico se define en D-001 | Acordado |
| RF-006 | Acceso de asesores mediante Cognito e invitación por correo | Las cuentas internas del MVP se crearán mediante invitación y autenticación de Cognito | Acordado |
| RF-007 | Un único rol funcional en el MVP: `ADVISOR` | No se implementarán roles de administrador/supervisor en el MVP. El modelo deberá poder evolucionar posteriormente | Acordado |

## 3.2 Conversaciones, mensajes y estados

| ID | Requerimiento funcional | Criterio / comportamiento esperado | Estado |
|---|---|---|---|
| RF-008 | Persistencia de conversaciones y mensajes | Cada mensaje persistido deberá almacenar al menos `conversation_id`, sender, timestamp, tipo de contenido y estado técnico | Acordado |
| RF-009 | Estados de conversación simplificados | La conversación usará: `BOT_ATENDIENDO`, `PENDIENTE_ASESOR`, `EN_ATENCION` y `CERRADA` | Acordado |
| RF-010 | Máximo configurable de conversaciones activas | Para anónimos el máximo es 1. Para autenticados el valor del MVP queda definido por D-002 | Parcial |
| RF-011 | La conversación cerrada no desaparece instantáneamente | El usuario verá que la conversación finalizó y tendrá una acción para iniciar una nueva. Reapertura/historial dependen de D-003 | Acordado |
| RF-012 | Historial completo disponible para el asesor | El asesor deberá poder consultar la conversación actual y conversaciones anteriores disponibles del usuario autenticado | Acordado |
| RF-013 | Contexto acotado para IA | Las llamadas de IA utilizarán como máximo una ventana reciente de aproximadamente 20 mensajes; no se enviará el historial completo. La estrategia de resumen queda en D-004 | Acordado |
| RF-014 | Límites configurables contra abuso | El sistema deberá soportar límites de cantidad de mensajes, longitud, frecuencia, imágenes y tamaño de conversación. Los valores se cierran en D-005 | Acordado |

## 3.3 IA, clasificación y FAQ/RAG

| ID | Requerimiento funcional | Criterio / comportamiento esperado | Estado |
|---|---|---|---|
| RF-015 | Haiku como capa de lectura y orquestación | Los mensajes elegibles deberán ser clasificados para decidir ruta de respuesta sin usar Gemini como clasificador general | Acordado |
| RF-016 | Intenciones mínimas del MVP | El sistema deberá distinguir al menos `FAQ`, `CATALOGO`, `ASESOR` y `OTRO`. Las consultas de información personal no habilitadas se derivarán a asesor | Acordado |
| RF-017 | FAQ basada en conocimiento VMC recuperado | Las respuestas FAQ se generarán a partir de documentos/contenido recuperado desde Pinecone y del system prompt autorizado | Acordado |
| RF-018 | Prohibición de inventar cuando no existe evidencia suficiente | Si la recuperación no entrega información suficiente, la respuesta no deberá completarse con conocimiento general; se deberá iniciar handoff | Acordado |
| RF-019 | Fuentes/enlaces cuando estén disponibles | La respuesta automática deberá incluir el enlace al centro de ayuda o fuente recuperada cuando exista | Acordado |
| RF-020 | Gemini como capa de escritura | Gemini recibirá el mensaje, contexto reciente y fragmentos recuperados para redactar la respuesta automática. No procesa los casos que ya pasan directamente a atención humana | Acordado |
| RF-021 | Tratamiento eficiente de mensajes triviales o repetitivos | El sistema deberá poder evitar consumo innecesario frente a saludos repetidos, spam o abuso. La regla exacta se define en D-006 | Parcial |

## 3.4 Derivación humana y tickets

| ID | Requerimiento funcional | Criterio / comportamiento esperado | Estado |
|---|---|---|---|
| RF-022 | Criterios de handoff | El sistema deberá poder derivar ante solicitud explícita de persona, baja confianza/no respuesta de RAG, repetición de consulta, frustración detectada u otras reglas definidas | Acordado |
| RF-023 | Ticket solo cuando existe atención humana | Una conversación automática puede existir sin ticket. El ticket representa trabajo que requiere intervención de asesor | Acordado |
| RF-024 | Recolección previa de datos requeridos por tipo de ticket | Antes de crear ciertos tickets, el bot podrá solicitar datos mínimos del caso. La taxonomía y campos se definen en D-008 | Parcial |
| RF-025 | Desactivación de IA al entrar en `PENDIENTE_ASESOR` | Una vez iniciado el handoff, la IA no seguirá respondiendo como bot mientras el caso espera asesor, salvo la política que se cierre en D-007 | Acordado |
| RF-026 | Mensajes del usuario durante espera se conservan | Todos los mensajes posteriores al handoff deberán almacenarse aunque la IA se encuentre deshabilitada | Acordado |
| RF-027 | Mensaje fijo de espera, máximo una vez por período pendiente | Si el usuario insiste mientras espera, podrá enviarse una única respuesta automática/determinística informando que la solicitud está en espera. No se repetirá ante cada mensaje | Acordado |
| RF-028 | Notificación inmediata por Slack | Al generarse un handoff/ticket deberá enviarse una notificación a Slack sin esperar a que un asesor tome la conversación | Acordado |
| RF-029 | Bandeja general y toma de conversación | Los asesores podrán visualizar pendientes y ejecutar “Tomar conversación”. La asignación deberá ser atómica para evitar que dos asesores tomen el mismo caso | Acordado |
| RF-030 | Sin límite funcional de conversaciones simultáneas por asesor en MVP | El sistema no impondrá un máximo de casos tomados por asesor durante el MVP | Acordado |
| RF-031 | Cierre manual por asesor | El asesor podrá cerrar el caso. El sistema registrará el cierre y podrá emitir un mensaje automático de finalización | Acordado |

## 3.5 Aplicación del asesor

| ID | Requerimiento funcional | Criterio / comportamiento esperado | Estado |
|---|---|---|---|
| RF-032 | Bandeja de conversaciones | La lista mostrará al menos nombre/identificador, último mensaje, tiempo de espera, canal web, estado, asesor asignado cuando aplique y contador de no leídos | Acordado |
| RF-033 | Vista de conversación e información contextual | El asesor podrá ver el hilo y datos disponibles/autorizados del usuario, como nombre, correo, empresa, identificadores y relaciones relevantes. Los campos definitivos se validan en D-010 | Parcial |
| RF-034 | Envío de mensajes de texto | El asesor podrá responder desde Subastín con texto, emojis, enlaces clickeables y copiar contenido | Acordado |
| RF-035 | Contador de no leídos | Los mensajes entrantes aún no abiertos por el asesor incrementarán un contador; al abrir la conversación quedarán consumidos para efectos de contador | Acordado |
| RF-036 | Timestamp por mensaje | Cada mensaje mostrado deberá incluir o permitir consultar su fecha/hora | Acordado |
| RF-037 | Retry de mensaje fallido sin persistir el fallo | Si un envío falla antes de confirmarse en backend, se mantendrá localmente en el navegador con opción Reintentar. No se persistirá como mensaje enviado hasta recibir confirmación | Acordado |
| RF-038 | Idempotencia de reintentos | Los reintentos deberán usar un identificador de cliente/idempotencia para evitar mensajes duplicados | Acordado |
| RF-039 | Funciones expresamente no incluidas en MVP | No habrá edición/borrado de mensajes, búsqueda dentro de conversación, read receipts ni indicador de “escribiendo” | Acordado |

## 3.6 Imágenes

| ID | Requerimiento funcional | Criterio / comportamiento esperado | Estado |
|---|---|---|---|
| RF-040 | Envío de imágenes en chat | El usuario podrá adjuntar imágenes; el asesor podrá visualizarlas | Acordado |
| RF-041 | Carga desde selector, pegado y drag & drop | La interfaz web soportará las tres formas de adjuntar imagen en los puntos donde se habilite carga | Acordado |
| RF-042 | Almacenamiento de imágenes en S3 | Las imágenes aceptadas deberán almacenarse fuera de la base de mensajes y referenciarse mediante metadatos/URL segura | Acordado |
| RF-043 | Interpretación de imágenes por IA | El MVP contempla que la IA pueda interpretar imágenes. Resize, compresión, límites y modelo quedan definidos en D-015 | Acordado |

## 3.7 Catálogo HERALD

| ID | Requerimiento funcional | Criterio / comportamiento esperado | Estado |
|---|---|---|---|
| RF-044 | Integración con HERALD | Subastín deberá consultar la API HERALD para resolver búsquedas de vehículos en tiempo real | Acordado |
| RF-045 | Mapeo de parámetros y resultados | Filtros, autenticación, paginación, imágenes, enlaces y estructura de salida se implementarán según documentación validada en D-011 | Parcial |
| RF-046 | Manejo controlado de indisponibilidad de HERALD | El sistema no deberá inventar catálogo cuando HERALD falle. La UX exacta y si ofrece handoff se define en D-012 | Parcial |

## 3.8 Dashboard operativo

| ID | Requerimiento funcional | Criterio / comportamiento esperado | Estado |
|---|---|---|---|
| RF-047 | Dashboard operativo para CSMs/asesores | El MVP deberá incluir una vista numérica de operación, no de administración técnica | Acordado |
| RF-048 | Métricas básicas de operación | El dashboard deberá poder mostrar volumen de conversaciones/tickets, pendientes, en atención, cerrados y tiempos de espera. El set final se valida en D-013 | Parcial |
| RF-049 | Sin panel de configuración técnica en MVP | Prompts, modelos IA, documentos, categorías, tags, costos y configuración avanzada no serán editables por asesores desde la interfaz MVP | Acordado |

## 3.9 Auditoría y datos VMC

| ID | Requerimiento funcional | Criterio / comportamiento esperado | Estado |
|---|---|---|---|
| RF-050 | Auditoría de acciones críticas | Se registrará como mínimo: handoff, creación/cierre de ticket, toma de conversación, cambios de estado, mensajes enviados por asesor, cierre y eventos administrativos futuros relevantes | Acordado |
| RF-051 | Solo lectura sobre información de VMC | Subastín no podrá modificar correo, teléfono, estados, subastas, vehículos u otros datos de VMC desde el chatbot | Acordado |
| RF-052 | Restricción de datos sensibles para el bot | El bot no deberá exponer información financiera detallada, documentos, datos internos ni información de otros usuarios. Cualquier dato personal futuro deberá estar explícitamente autorizado | Acordado |
| RF-053 | Retención configurable | Conversaciones e imágenes deberán soportar una política de retención; se propone 6 meses, pendiente de D-014 | Parcial |

---

# 4. Requerimientos no funcionales (RNF)

| ID | Requerimiento | Objetivo MVP | Notas |
|---|---|---|---|
| RNF-001 | Latencia de respuesta automática | ≤ 10 s en condiciones normales | No implica esperar 10 s; es un máximo objetivo |
| RNF-002 | Disponibilidad | 99% | Objetivo de MVP, sujeto a dependencias externas |
| RNF-003 | Durabilidad de mensajes | Persistencia confirmada antes de mostrarse como enviado | Excepto borrador local de retry fallido |
| RNF-004 | Idempotencia | Sin duplicados por retries/webhooks | Aplicar claves idempotentes y deduplicación |
| RNF-005 | Seguridad de identidad | No confiar en identidad enviada libremente por frontend | Mecanismo VMC ↔ Subastín se cierra en D-001 |
| RNF-006 | Observabilidad | Logs, métricas y alertas | CloudWatch u observabilidad equivalente |
| RNF-007 | Protección de costo/abuso | Límites configurables | Valores concretos en D-005/D-006 |
| RNF-008 | Optimización multimodal | No enviar imágenes originales innecesariamente a IA | Resize/compresión según D-015 |

---

# 5. Reglas de negocio (RB)

| ID | Regla |
|---|---|
| RB-001 | Un usuario anónimo puede utilizar el bot sin entregar datos |
| RB-002 | El correo se solicita al anónimo únicamente cuando se necesita handoff humano |
| RB-003 | Un anónimo no recupera historial entre sesiones/dispositivos |
| RB-004 | Un usuario autenticado se asocia a una identidad validada por VMC |
| RB-005 | Una conversación no implica necesariamente un ticket |
| RB-006 | Un ticket representa una necesidad de atención humana |
| RB-007 | Durante `PENDIENTE_ASESOR` la IA queda deshabilitada según política D-007 |
| RB-008 | Un handoff genera notificación de Slack inmediatamente |
| RB-009 | La IA no debe responder FAQ fuera de las fuentes autorizadas cuando no existe evidencia suficiente |
| RB-010 | Subastín no modifica datos de VMC |
| RB-011 | WhatsApp/Kapso no forma parte de la conversación web unificada del MVP |

---

# 6. Decisiones pendientes (D)

Todas las decisiones de esta sección tienen como responsables de cierre a **Silvana + Julio**. Cuando corresponda, pueden requerir apoyo de Desarrollo/HERALD.

Hasta su cierre no deben convertirse en supuestos técnicos ocultos.

| ID | Decisión | Qué debe cerrarse | Prioridad |
|---|---|---|---|
| D-001 | Mecanismo de identidad VMC ↔ Subastín | Definir si la integración será iframe, script embebido, endpoint autenticado/token corto, servidor-servidor u otra opción. Validar cookies HttpOnly/SameSite y seguridad | Alta |
| D-002 | Máximo de conversaciones activas para usuario autenticado | Definir 1 conversación activa —recomendado para simplificar MVP— vs. hasta 3. Anónimo queda fijo en 1 | Alta |
| D-003 | Cierre, reapertura e historial visible | Definir inactividad para autocierre del bot, ventana de reapertura, creación de nueva conversación y cuántas conversaciones cerradas ve el usuario | Alta |
| D-004 | Resumen de conversación para IA | Definir si siempre se genera resumen, cada cuántos mensajes, tamaño objetivo, cuándo se actualiza y si se usa junto a los últimos 20 mensajes | Media |
| D-005 | Guardrails cuantitativos | Definir máximo de mensajes por conversación —ej. 1,000—, tamaño de mensaje, rate limit, cantidad/tamaño de imágenes, límites por usuario/IP y política frente a abuso | Alta |
| D-006 | Optimización de saludos/spam/repetición | Definir qué mensajes no ameritan llamada completa a IA y cuándo se usa respuesta determinística, cooldown o bloqueo temporal | Media |
| D-007 | Duración del modo IA OFF durante handoff | Definir si permanece apagada hasta que un asesor cierre el caso —recomendado— o si existe expiración/reevaluación, por ejemplo 8 h | Alta |
| D-008 | Taxonomía de problemas y tickets | Definir tipos de problema, qué genera ticket, campos obligatorios por tipo, área responsable, prioridad y criterios de cierre | Alta |
| D-009 | Tags de negocio | Definir si existirán en MVP, catálogo inicial y si los asigna IA, asesor o ambos con edición manual | Media |
| D-010 | Campos de usuario visibles y utilizables | Definir exactamente qué campos llegan desde VMC/JWT/API y cuáles puede ver el asesor o usar el bot: nombre, email, empresa, DNI, vehículos, etc. | Alta |
| D-011 | Contrato HERALD | Validar documentación: endpoints, auth, filtros, paginación, timeout, formato, imágenes, URLs, límites y errores | Alta |
| D-012 | Fallback cuando HERALD no está disponible | Definir mensaje al usuario y si se ofrece/crea handoff automáticamente | Media |
| D-013 | Métricas exactas del dashboard operativo | Definir tarjetas, ventanas de tiempo, fórmulas y métricas mínimas para CSMs/asesores | Media |
| D-014 | Retención de conversaciones e imágenes | Confirmar 6 meses u otro período y comportamiento de borrado/archivo | Alta |
| D-015 | Procesamiento de imágenes para IA | Definir dimensiones máximas, compresión/resize, formato, peso máximo, modelo multimodal y cuándo una imagen se envía a IA | Media |
| D-016 | Canal Slack y formato de notificación | Definir canal/es, contenido mínimo, enlace profundo a Subastín y posibles re-alertas por espera | Baja |
| D-017 | Relación conversación ↔ ticket | Confirmar si una conversación puede tener múltiples tickets y si cerrar un ticket cierra o no la conversación | Alta |
| D-018 | Sesión anónima activa | Definir duración técnica de la sesión anónima mientras el usuario permanece navegando y qué sucede al refrescar/cerrar navegador | Media |
| D-019 | Handoff anónimo sin correo | Definir qué hacer si el usuario no entrega correo: impedir ticket, permitir ticket sin contacto o mantener conversación automática | Media |
| D-020 | Debounce/agregación de mensajes consecutivos | Definir ventana corta para agrupar mensajes antes de llamar a IA y evitar múltiples llamadas por frases partidas | Media |

---

# 7. Fuera de alcance del MVP / preparado para futuro

- Chatbot inbound por WhatsApp dentro de Subastín.
- Timeline omnicanal unificada Web + WhatsApp.
- Audio y transcripción de mensajes.
- Edición o borrado de mensajes enviados.
- Búsqueda dentro de conversaciones.
- Read receipts e indicador de “escribiendo”.
- Exportación de conversaciones.
- Sugerencias IA al asesor y copiloto de atención.
- Panel para modificar prompts, modelos IA, documentos, categorías, tags o costos.
- Roles `ADMIN/SUPERVISOR` completos.
- Modificación de datos del usuario en VMC.
- Métricas analíticas avanzadas, costos IA y configuración operativa avanzada.

---

# 8. Escenarios de aceptación críticos — Spec-Driven

## AC-001 · FAQ anónima

**Dado** un usuario no autenticado sin datos personales,  
**cuando** envía una pregunta FAQ con evidencia suficiente en la base de conocimiento,  
**entonces** Subastín debe responder automáticamente sin solicitar correo y guardar únicamente la sesión activa.

## AC-002 · FAQ sin evidencia

**Dado** un mensaje cuya recuperación no contiene evidencia suficiente,  
**cuando** Haiku/RAG determina que no puede responderse de forma segura,  
**entonces** el sistema debe iniciar handoff en lugar de inventar una respuesta.

## AC-003 · Handoff anónimo

**Dado** un usuario anónimo que necesita asesor,  
**cuando** se inicia el handoff,  
**entonces** Subastín debe solicitar correo antes de completar el ticket y notificar a Slack al generarse el caso.

## AC-004 · Espera de asesor

**Dado** un caso en `PENDIENTE_ASESOR`,  
**cuando** el usuario envía mensajes adicionales,  
**entonces** los mensajes se almacenan, la IA no responde como bot y el mensaje fijo de espera no se repite indefinidamente.

## AC-005 · Toma concurrente

**Dado** un ticket pendiente visible para dos asesores,  
**cuando** ambos intentan tomarlo casi simultáneamente,  
**entonces** solo uno obtiene la asignación y el otro recibe un estado actualizado sin duplicar atención.

## AC-006 · Retry

**Dado** un mensaje del asesor cuyo envío falla antes de confirmación,  
**cuando** el frontend muestra Reintentar y el asesor reintenta,  
**entonces** el backend debe persistir una sola copia del mensaje confirmado.

## AC-007 · Imagen

**Dado** un usuario que adjunta una imagen válida,  
**cuando** se completa la carga,  
**entonces** la imagen queda almacenada en S3 y disponible para el asesor; el procesamiento para IA seguirá D-015.

## AC-008 · Usuario autenticado

**Dado** un usuario autenticado en VMC,  
**cuando** abre Subastín,  
**entonces** el sistema debe asociar la conversación a la identidad validada y permitir saludo por nombre, sin confiar en un `user_id` manipulable por frontend.

## AC-009 · Conversación cerrada

**Dado** una conversación en estado `CERRADA`,  
**cuando** el usuario vuelve a la interfaz,  
**entonces** debe visualizar que el caso finalizó y disponer de una acción para iniciar una nueva conversación según D-003.

---

# 9. Definition of Done del MVP

- Los RF marcados como **Acordado** están implementados y validados.
- Las decisiones D de prioridad **Alta** que bloqueen comportamiento o seguridad están cerradas y reflejadas en el spec.
- Los flujos FAQ, catálogo, handoff, toma de asesor, cierre, imágenes y retry cuentan con QA end-to-end.
- La identificación VMC no depende de datos manipulables por el cliente.
- Los eventos críticos tienen trazabilidad/auditoría.
- La aplicación cumple el objetivo de latencia automática **≤ 10 s** en condiciones normales y disponibilidad objetivo de **99%**.
- Las funcionalidades fuera de alcance no bloquean el modelo de datos ni requieren reescribir la arquitectura para habilitarlas posteriormente.
