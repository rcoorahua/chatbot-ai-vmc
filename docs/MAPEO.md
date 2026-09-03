# MAPEO.md — Intenciones, flujos guiados y quick replies (D-028)

**Fecha:** 2026-09-01 · **Decisión:** Aaron · **Fuente analizada:** Centro de Ayuda completo
(22 artículos, 111 preguntas + 22 respuestas rápidas = 133 chunks, corrida de
`scripts.helpcenter_fetch` del 2026-09-01, ver `data/helpcenter/README.md`).

Este documento responde tres preguntas y deja cerrada la **D-028 (flujos guiados)**:

1. ¿Qué intenciones existen en el corpus y cuáles necesitan **estado** (un flujo con pasos)
   versus cuáles son **FAQ planas** (pregunta → RAG → respuesta, sin memoria)?
2. ¿Dónde se guarda ese estado y qué relación tiene con el contexto de la conversación?
3. ¿Cómo viajan los botones (quick replies) sin abrir un agujero de seguridad?

---

## 1. Por qué hace falta estado (el problema en una tabla)

El RAG busca **solo con el texto del mensaje actual** (`ai_worker._answer_faq`). Consultas
reales contra el índice (scores sobre el umbral 0.84):

| Consulta del usuario | Resultados sobre el umbral |
|---|---|
| "Quiero participar" | 0 |
| "En Vivo" | 0 |
| "Sí" | 0 |
| "Quiero participar en una subasta En Vivo" | 4 |
| "Cómo consigno para participar" | 4 |

Si el bot pregunta *"¿En Vivo o Negociable?"* y el usuario contesta **"En Vivo"**, la
búsqueda literal de "En Vivo" no supera el umbral → "sin evidencia" → para un autenticado,
**handoff innecesario**. La solución: recordar qué dato se está esperando (estado) y, al
recibirlo, buscar con una **consulta canónica** ("Cómo participar en una oferta En Vivo")
que sí recupera evidencia.

**Fórmula:** LLM/reglas (entender) → Estado (recordar qué se espera) → Botones (respuestas
estructuradas) → RAG con consulta canónica (explicar) → HERALD (cuando exista, D-011).

## 2. Dónde vive el estado — respuestas directas

**¿Se guarda en DynamoDB?** Sí: como **atributos opcionales de la fila de `Conversations`**
(no una tabla nueva — la conversación es permanente por D-003 y ya es el lugar natural; el
repositorio ya domina las actualizaciones condicionales que esto necesita):

```json
{
  "active_flow": "PARTICIPATION",
  "flow_step": "SELECT_OFFER_TYPE",
  "flow_slots": {"offer_type": null},
  "flow_version": 7,
  "flow_expires_at": "2026-09-02T18:00:00Z"
}
```

**¿Es aparte del contexto de mensajes?** Sí, completamente. El contexto del redactor son los
últimos **20 mensajes de la última hora** (D-004 — no 10) y es efímero: pasada la ventana, el
mensaje se atiende solo. El estado de flujo es **duradero y explícito**: sobrevive a la
ventana, tiene su propio vencimiento (24 h) y se limpia por eventos concretos (respuesta
recibida, handoff, cierre, vencimiento). Uno es *memoria de lectura* para redactar; el otro
es *posición en un proceso*.

**Por qué `flow_version`:** la conversación autenticada es permanente (D-003). Un botón
renderizado hace 5 días no debe mover el flujo de hoy: cada quick reply viaja con la versión
del flujo que la creó y el servidor ignora versiones viejas. También hace **atómica** la
transición (ConditionExpression sobre `flow_version`) entre dos pestañas o dos jobs.

## 3. Botones (quick replies) como eventos estructurados

El mensaje del bot lleva las opciones en `metadata` (el modelo `Message.metadata` ya existe
y el API ya lo devuelve al widget):

```json
{
  "content": "¿En qué tipo de oferta quieres participar?",
  "metadata": {"interaction": {
    "type": "QUICK_REPLIES",
    "action_id": "SELECT_OFFER_TYPE",
    "flow_version": 7,
    "options": [
      {"label": "Oferta En Vivo", "value": "LIVE"},
      {"label": "Oferta Negociable", "value": "NEGOTIABLE"}
    ]
  }}
}
```

El clic **no** manda solo texto: manda el texto visible (para el hilo) **más** el evento:

```json
{
  "client_message_id": "…",
  "content": "Oferta En Vivo",
  "interaction": {"action_id": "SELECT_OFFER_TYPE", "value": "LIVE", "flow_version": 7}
}
```

**Seguridad (regla de `security-guidance`):** el servidor valida `action_id`, `value` y
`flow_version` contra el paso vigente de la conversación. Editar el HTML no permite inventar
acciones: un evento que no coincide con el paso actual se trata como texto normal y sigue el
pipeline de siempre (clasificador → RAG). Los `value` aceptados son un enum cerrado por paso.

### 3.1 Botones SIN estado: preguntas hermanas y chip de fuente (D-030, 2026-09-03)

Bajo cada respuesta con evidencia, las **otras preguntas del mismo artículo** salen como
botones (`agent/related.py`): hasta 3, sin la que se acaba de responder y sin la
introducción del artículo (que no es una pregunta). La fuente va aparte, como chip:

```json
{
  "content": "Para registrarte: 1) entra a vmcsubastas.com y pulsa Ingresar, 2) …",
  "metadata": {
    "rag_query": "¿Cómo me registro en VMC?",
    "sources": [{"title": "¡Registrarte es fácil y rápido!", "url": "https://…/registrarte-es-facil-y-rapido"}],
    "interaction": {
      "type": "RELATED_QUESTIONS",
      "action_id": "RELATED_QUESTION",
      "options": [
        {"label": "¿Puedo registrarme como persona jurídica?", "value": "Q1",
         "query": "¿Puedo registrarme como persona jurídica?"}
      ]
    }
  }
}
```

El clic manda el texto visible más `{"action_id": "RELATED_QUESTION", "value": "Q1"}`, **sin
`flow_version`** (no hay estado que versionar). El worker lo valida contra la metadata del
**último mensaje del bot** (la `query` se lee de ahí, nunca del clic) y manda esa pregunta al
RAG **sin clasificador** (`related:model` en AIUsage). Un clic sobre botones viejos o con un
`value` inventado se degrada a texto normal. A diferencia de los flujos de §4.1, escribir otra
cosa no "interrumpe" nada: los botones simplemente quedan atrás. Por qué existe: reemplaza al
"¿te explico el siguiente paso?" del redactor, que costaba una llamada entera por cada "sí"
(D-030 en CLAUDE.md).

Cada opción lleva `kind`: `question` (las de arriba) o `handoff`. La de `handoff` es el botón
**"Contactar con un asesor"** (`value: "ADVISOR"`, sin `query`), que aparece solo cuando la
respuesta o su evidencia mandan a contactar al equipo (`related.suggests_advisor`, regex sin
modelo); su clic abre el formulario de D-029 directamente, sin clasificador, sin cuota y sin
modelo (`handoff_offer:related_button`). La pregunta **respondida** (la que no se ofrece) se
detecta por parecido con la consulta, no por score: con "Hola como me registro" el índice puso
persona jurídica primero y el botón repetía "¿Cómo me registro?".

## 4. El mapeo completo del corpus

Regla de diseño: **un flujo solo existe si la respuesta correcta depende de un dato que el
usuario aún no dio** (un slot). Si la pregunta se responde con un chunk, es FAQ plana — meter
estado ahí es burocracia. De las 111 preguntas, **~90 son FAQ planas**.

### 4.1 Flujos CON estado

**F-PART · PARTICIPATION — "quiero participar"** ⬅ *implementado en esta fase*

| Paso | Espera | Botones | Al resolver |
|---|---|---|---|
| `SELECT_OFFER_TYPE` | `offer_type` | `Oferta En Vivo` → `LIVE` · `Oferta Negociable` → `NEGOTIABLE` | RAG canónico por valor |

- Disparadores (reglas, sin IA): "quiero participar", "cómo participo", "deseo participar",
  "quiero entrar a la subasta / ofertar / pujar" sin tipo de oferta en el texto.
- Si el mensaje YA trae el tipo ("quiero participar en una en vivo") → **no hay botones**:
  se extrae `offer_type` y va directo al RAG canónico. El flujo ni se persiste.
- Consultas canónicas: `LIVE` → *"Si quiero participar en una oferta En Vivo hoy, ¿qué tengo
  que hacer?"* · `NEGOTIABLE` → *"¿Qué significa oferta Negociable y cómo inicio una
  negociación para participar?"* (ambas verificadas con ≥4 resultados sobre el umbral).
- Cobertura del corpus: artículos "¡Consignar es necesario para participar!", "La oferta En
  Vivo: aquí está la información", "La oferta En Vivo: es hora de participar", "La oferta
  Negociable: ¿cómo funciona?".

**F-CONS · CONSIGNMENT — "quiero consignar / cómo consigno"** ✅ *activado 2026-09-01*

| Paso | Espera | Botones |
|---|---|---|
| `SELECT_OFFER_TYPE` | `offer_type` | los mismos dos |

El corpus separa la consignación "En Vivo" de la "Negociable" (dos preguntas distintas en
"¡Consignar es necesario para participar!"). Mismo esqueleto que F-PART con otras consultas
canónicas. Se activa agregando una entrada en `agent/flows.py`, sin tocar el motor.

**F-LIVE · LIVE_STAGE — "¿y ahora qué?" dentro de una oferta En Vivo** ✅ *activado 2026-09-01*

| Paso | Espera | Botones |
|---|---|---|
| `SELECT_STAGE` | `stage` | `Antes de empezar` / `Durante la puja` / `Terminó el proceso` / `Resulté ganador` |

Cobertura: "Es hora de participar" (durante), "El proceso terminó" (después), "Gané una
oferta En Vivo" (ganador — distingue Ganador Directo vs Mejor Postor, que podría ser un
segundo slot si los datos lo piden).

**F-NEGO · NEGOTIATION_STAGE — estado de una negociación** ✅ *activado 2026-09-01*

| Paso | Espera | Botones |
|---|---|---|
| `SELECT_STAGE` | `stage` | `Envié mi propuesta` / `Me aceptaron` / `Contrapropuesta` / `Rechazada` |

Cobertura: "La oferta Negociable: ¿cómo funciona?" (aceptación, contrapropuesta, rechazo).

**F-HAB · ENABLEMENT — "me habilitaron, ¿qué hago?"** ✅ *activado 2026-09-01*

| Paso | Espera | Botones |
|---|---|---|
| `SELECT_TOPIC` | `topic` | `Pagar la comisión` / `Subir documentos` / `Pagar la oferta` / `Mi comprobante` |

Cobertura: "¡He sido habilitado para comprar!" (11 preguntas — el artículo más largo del
corpus, y todas sus preguntas empiezan igual: candidato natural a desambiguar con botones).

### 4.2 FAQ planas (RAG directo, SIN estado) — el resto del corpus

| Tema (artículo) | Ejemplos de intención | Por qué no lleva estado |
|---|---|---|
| Registro | "cómo me registro", "olvidé mi contraseña", "persona jurídica" | cada pregunta se autocontiene |
| Comisión | "cuánto es la comisión", "mi bid la incluye", "por qué se paga" | ídem |
| Fee de pasarela | "qué es el fee", "comprobante", "evitar el fee" | ídem |
| SubasCoins | "qué son", "cómo compro", "mínimo/máximo", "recibo VMC" | ídem |
| SubasPass / Puntos VMC | "qué es", "costo", "canje vs compra", "cuál conviene" | comparación en un solo chunk |
| Recarga | "qué es", "cómo recargo", "dónde está mi C.U.U." | ídem |
| Devoluciones | "devuélvanme mi saldo", "por qué me dieron SubasCoins" | ídem |
| Consignación-devolución | "cuándo me devuelven la consignación" | ídem (≠ F-CONS: esto es posterior) |
| Riesgo Usuario | "qué es", "por qué soy Alto", "cómo mejoro" | ídem |
| Visitas | "cómo agendo", "acompañantes", "inspección mecánica" | ídem |
| Deudas | "por qué tengo deuda", "cómo la pago" | ídem |
| Sanciones | "qué pasa si incumplo", "no pude entrar a la sala" | ídem |
| Código Pacífico | "cómo uso el código de pago" | ídem |
| Conceptos En Vivo/Negociable | "qué es un bid", "precio base/reserva", "desde el celular" | definiciones sueltas |

**Interrupciones:** una FAQ plana en medio de un flujo se responde normal y el flujo
**se conserva** hasta su vencimiento (el usuario puede volver con el botón o con texto).
Lo que SÍ limpia el flujo: resolver el paso, handoff, cierre del ticket, guardrail de
seguridad, o el vencimiento de 24 h.

**Anónimos:** los flujos funcionan igual (son FAQ guiadas, no requieren identidad). El
handoff sigue las reglas de D-002.

## 5. Qué NO es esto

- **No es LangGraph.** El worker ya orquesta secuencialmente (guardrails → clasificación →
  RAG → redacción → handoff). Un checkpointer externo sumaría persistencia paralela a
  DynamoDB para un problema que hoy es UN paso con UN slot. Se reevalúa si algún día hay
  flujos largos con ciclos, tools encadenadas y aprobaciones humanas intermedias.
- **No lista subastas reales.** HERALD sigue siendo stub (D-011 abierta): F-PART explica el
  procedimiento, no muestra ofertas disponibles. Cuando D-011 cierre, el paso resuelto puede
  además consultar el catálogo.
- **No convierte las 111 preguntas en estados.** Solo 5 grupos justifican flujo; el resto es
  y seguirá siendo RAG plano.

## 6. Contabilidad y costos (regla llm-cost-optimizer)

- Mostrar los botones **no llama a ningún modelo**: detección por reglas → `AIUsage` con
  `provider=NONE`, `source=flow:PARTICIPATION:offered`.
- Resolver el paso hace **una** llamada al redactor (la misma que una FAQ), con la consulta
  canónica; `source=flow:PARTICIPATION:resolved`.
- Un clic de botón **no** pasa por el clasificador: la intención ya viene estructurada.
  Flujos = *menos* llamadas IA, no más.

## 7. Estado de implementación

| Pieza | Estado |
|---|---|
| Motor de flujos (`agent/flows.py`) + F-PART | ✅ esta fase |
| Campos de flujo en `Conversations` + transición atómica | ✅ esta fase |
| Quick replies en `metadata` + validación servidor | ✅ esta fase |
| Render de botones en el widget + evento de clic | ✅ esta fase |
| F-CONS · F-LIVE · F-NEGO · F-HAB | ✅ activados 2026-09-01 — 16 consultas canónicas verificadas contra el índice (todas con 4 fragmentos sobre el umbral, scores 0.885–0.935) |
| Preguntas hermanas + chip de fuente bajo cada respuesta (D-030, §3.1) | ✅ 2026-09-03 — sin estado, `agent/related.py`; el clic va al RAG sin clasificador |
| HERALD en el paso resuelto | ⛔ bloqueado por D-011 |

---

> **Nota (2026-09-02):** además de los flujos del corpus, `agent/flows.py` define
> `HANDOFF_CONFIRM`, que **no sale de este mapeo**: es la pregunta de sí/no que el bot abre
> cuando se queda sin evidencia, para no empujar el formulario de asesor sin preguntar
> (revisión de D-029). Usa la misma maquinaria de estado por la misma razón — hay que recordar
> que se preguntó algo y validar la respuesta contra ese paso — pero su resolución no consulta
> el índice, así que no tiene consultas canónicas y vale solo para el turno siguiente.

## 8. Tipos de ticket que el corpus sugiere — INSUMO para D-008 (⚠️ propuesta, NO cierra la decisión)

**D-008 (taxonomía de tickets) sigue ABIERTA y es de Silvana + Julio.** Esta sección es el
análisis técnico que la alimenta: leyendo las 111 preguntas del Centro de Ayuda, estos son
los motivos por los que un usuario **realmente** necesita a un humano — es decir, lo que un
asesor va a encontrarse en su bandeja y va a querer filtrar/priorizar. La forma sigue el
esquema previsto en la tabla Tickets (`problem_type`, `category`, `tags`).

Criterio: un tipo de ticket existe si el corpus muestra un problema que **el bot no puede
resolver ni con evidencia** (requiere mirar la cuenta del usuario, mover dinero, o decidir).
Lo que el corpus responde bien es FAQ/flujo, no ticket.

| `problem_type` propuesto | Cuándo se abre (señales en el corpus) | `category` | Prio sugerida | Datos mínimos que el asesor necesita |
|---|---|---|---|---|
| `PAYMENT_ISSUE` | "ya pagué y no se refleja", problemas con código de pago Pacífico, fee cobrado dos veces | `BILLING` | **Alta** | id de oferta, medio de pago, fecha del pago, monto |
| `REFUND_REQUEST` | "devuélvanme mi saldo en US$", "me devolvieron SubasCoins y yo pagué en dólares", consignación no liberada | `BILLING` | Alta | monto, moneda original, fecha de recarga/consignación |
| `DEBT_DISPUTE` | "por qué tengo una deuda", "no estoy de acuerdo con el monto", quiere regularizar para volver a participar | `BILLING` | Media | id de la oferta que la originó, monto |
| `SANCTION_APPEAL` | "no pude entrar a la sala por mi internet, ¿me sancionan igual?", "el proceso cerró sin que pueda bidear", apelar una sanción | `COMPLIANCE` | **Alta** | id del proceso, fecha/hora, evidencia del problema |
| `ENABLEMENT_ISSUE` | documentos rechazados o sin respuesta tras subirlos, plazo de pago por vencer, "ya pagué y subí todo, ¿ahora qué?" atascado | `PURCHASE` | **Alta** (hay plazos que corren) | id de oferta ganada, qué paso está trabado |
| `RECEIPT_REQUEST` | "necesito mi boleta/factura del proceso terminado" | `PURCHASE` | Baja | id de oferta, razón social/RUC si es factura |
| `ACCOUNT_ACCESS` | "el formulario me impide registrarme", recuperación de contraseña que no llega, registro de persona jurídica trabado | `ACCOUNT` | Media | correo registrado, mensaje de error |
| `RISK_CATEGORY_DISPUTE` | "por qué mi Riesgo Usuario es Alto", perdió Puntos VMC y no sabe por qué, canje que no se aplicó | `ACCOUNT` | Media | — (el asesor lo ve en la cuenta) |
| `VISIT_ISSUE` | no puede agendar, quiere inspección mecánica y el sistema no lo deja, visita agendada sin confirmación | `LOGISTICS` | Media | id de oferta, fecha deseada |
| `PLATFORM_BUG` | la sala no carga, los bids no entran, errores repetidos al pujar ("ya van 3 veces que sale error") | `TECHNICAL` | **Alta** durante un proceso En Vivo | dispositivo/navegador, id del proceso, hora |
| `FORMAL_COMPLAINT` | "quiero presentar un reclamo" (el corpus lo menciona explícitamente → libro de reclamaciones) | `COMPLIANCE` | **Alta** (plazo legal) | descripción del reclamo; el resto lo pide el proceso formal |
| `OTHER` | todo lo que no calce; el asesor lo re-clasifica al cerrar | — | Media | — |

**`tags` transversales sugeridos** (D-009, también abierta): `EN_VIVO` / `NEGOCIABLE` (tipo
de oferta), `GANADOR` (el usuario ganó el proceso), `PLAZO_CORRIENDO` (habilitación o pago
con fecha límite), `RECURRENTE` (mismo usuario, mismo problema, segunda vez).

**Conexiones con lo ya construido:**
- El `handoff_reason` que hoy guarda la conversación (`advisor_request`, `faq_no_evidence`,
  reglas de frustración) es la **semilla** del `problem_type`: cuando exista el módulo
  Tickets (F5), el motivo del handoff pre-llena el tipo y el asesor lo confirma o corrige.
- Los flujos guiados (§4.1) reducen tickets: F-HAB bien respondido evita `ENABLEMENT_ISSUE`
  triviales; los que lleguen igual, llegan mejor clasificados (el flujo ya sabe la etapa).
- `PLATFORM_BUG` durante un En Vivo es el más urgente del mapa: el proceso corre en tiempo
  real y una falla de sala equivale a un `SANCTION_APPEAL` seguro después.

**Estado (2026-09-02): esta propuesta está IMPLEMENTADA** en
[`backend/tickets/taxonomy.py`](../backend/tickets/taxonomy.py) — los 12 tipos con su categoría,
su prioridad y sus datos mínimos, más las etiquetas de D-009 y las reglas por palabras clave
que sugieren el tipo sin llamar a ningún modelo. **Eso NO cierra D-008.** Se implementó para
que la decisión se tome con datos en vez de en abstracto: cada ticket guarda si el tipo lo
puso la regla o lo corrigió una persona (`classification_source`), así que a la vuelta de unas
semanas de uso se puede ver qué tipos sobran, cuáles faltan y cuántos casos caen en `OTHER`.
La prioridad sube un escalón cuando algo corre (`EN_VIVO`, `PLAZO_CORRIENDO`), que es como se
implementó el "Alta durante un proceso En Vivo" de la tabla.

**Qué falta para cerrar D-008 de verdad (decisión de Silvana + Julio):** validar esta lista
contra los motivos reales de contacto que hoy ve el equipo en Intercom, definir los campos
obligatorios por tipo, y decidir la prioridad operativa (SLA) de cada uno. Cerrarla con otra
lista es editar `backend/tickets/taxonomy.py` y sus tests: la taxonomía no está repartida por
el backend.
