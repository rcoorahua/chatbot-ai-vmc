# Decisiones del proyecto (texto completo)

Movido desde `CLAUDE.md` el 2026-11-20 sin cambios de contenido. `CLAUDE.md` guarda el resumen
de una línea por decisión; aquí está el detalle, la historia y los motivos. Al cerrar una
decisión: moverla a "cerradas" aquí, actualizar su línea en `CLAUDE.md` y reflejarla en PLAN.md.

## Decisiones técnicas cerradas (no re-discutir)

- **T1** HTTP API (API Gateway v2), no REST API. JWT authorizer nativo de Cognito para `/advisor` y `/dashboard`.
- **T2** Backend FastAPI completo en UNA Lambda con Mangum (`lifespan="off"`), ruta `$default`.
- **T3** Workers SQS en Lambdas separadas (`worker-ai`, `worker-notify`); la API solo encola y responde 202. Workers devuelven `batchItemFailures`.
- **T4** Infra con CDK v2 en Python (`infra/`), un stack por stage vía `-c stage=stage|prod`.
- **T5** dev = local con Docker (dynamodb-local + localstack sqs/s3, sin cuenta AWS); stage/prod = CDK.
- **T6** FastAPI se mantiene como framework (compatible con Lambda vía Mangum).
- **T7** Datos/estados/código en inglés (`PENDING_ADVISOR`…); UI en español; docs en español.
- **T8** Respuesta IA asíncrona: POST → 202 + SQS; el frontend hace polling.
- **T9** ~~Haiku para clasificación; Gemini para redacción.~~ **Superada provisionalmente por
  TD-008** (2026-08-27): Gemini (SDK `google-genai`) atiende ambas etapas. Haiku
  (`claude-haiku-4-5`) sigue siendo el plan B para clasificar si el golden set lo justifica.
- Modelo de datos: 5 tablas DynamoDB (`Conversations`, `Messages`, `Tickets`, `Advisors`, `AIUsage`) — claves/GSIs en PLAN.md §4, con los ajustes 1–5 de la revisión (unread_count, wait_message_sent, TTL en Messages, idempotencia transaccional, GSI sparse opcional).
- `visibility_timeout` de cada cola ≥ 6× el timeout de su worker.
- Los GSI se deciden ANTES de crear tablas en stage (backfill posterior es migración manual).

## Decisiones de NEGOCIO cerradas (2026-08-27, Aaron)

Reflejadas en PLAN.md §2/§4/§9 y REQUERIMENTS.md §6. Código: `core/auth.py`,
`conversations/service.py`, `widget/`.

> **2026-09-02 — D-029 revisa D-002, D-003, D-017, D-019 y D-023** (ver la última viñeta de
> esta sección). Sus textos originales se conservan abajo como historia; donde choquen, manda
> D-029: el autenticado tiene hilo + casos y "cerrar" un caso lo deja `CLOSED`.
> **2026-09-05 — D-031 revisa a su vez la parte anónima de D-029 y el badge de D-030**: el
> anónimo **NO** pide asesor ni deja datos y **ningún asesor lo toma**; solo FAQ y solo el
> bot, y para hablar con una persona se le manda a iniciar sesión. El asesor se sugiere
> únicamente dentro de la conversación (último mensaje sugerido), sin botón en la UI.

- **D-001 Identidad VMC ↔ Subastín**: JWT de identidad **firmado por el servidor de VMC** (HS256,
  secreto compartido `VMC_IDENTITY_SECRET`), dejado en la página como
  `window.subastinSettings.userJwt` y verificado en `POST /chat/sessions`, que devuelve un token de
  sesión propio (`SESSION_SIGNING_KEY`). Es la "identity verification" de Intercom en su variante
  vigente (JWT; el `user_hash` está deprecado). **Ajuste técnico sobre lo pedido** ("el widget lee
  la cookie"): `subastop_jwt` y `subastop_auth_user` son **HttpOnly** —ningún script puede
  leerlas— y compartir el secreto de sesión de VMC dejaría a Subastín forjar sesiones de VMC.
  Contrato para VMC en `widget/README.md`. La identidad visible del asistente es **"Subastín"**.
- **D-002 Conversaciones activas**: **1** por usuario (autenticado y anónimo). Máximo **5 tickets
  activos** por usuario (se aplica en F5). **Anónimo = solo FAQ**: sin handoff ni ticket, porque no
  hay forma de identificarlo para continuar un ticket días después; el widget lo invita a iniciar
  sesión. Consecuencias: cierra **D-019** (no existe el ticket anónimo) y deja **RF-003 / AC-003 /
  RB-002 sin efecto** — el spec aún dice "correo obligatorio al derivar anónimo"; hay que retirarlos
  o confirmar la lectura alternativa (ticket anónimo que muere con la sesión).
- **D-003 Cierre e historial**: **una sola conversación permanente** por usuario autenticado; no se
  crea otra ni se "reabre". Lo que se cierra son los **tickets**, que quedan en el hilo como notas
  de sistema (mensaje SYSTEM `TICKET_CLOSED` → "Ticket cerrado"), igual que las notas de Intercom.
  Cierra también **D-017**: N tickets por conversación (máx. 5 activos) y cerrar un ticket **no**
  cierra la conversación. El autocierre de un ticket sin respuesta quedó descartado por D-007
  (cerrada 28/08: nada se cierra ni se re-enciende solo).
- **D-018 (provisional, derivada de RF-004)**: sesión anónima = la pestaña del navegador
  (`sessionStorage`) con token de 24 h (`ANONYMOUS_SESSION_TTL_HOURS`). Confirmar con Silvana + Julio.
- **D-021 Alta de asesores**: auto-alta `ACTIVE` al primer login con JWT válido de Cognito
  (`advisors/service.py`). La invitación en Cognito es el único control; `DISABLED` se rechaza.
- **D-022 Quién responde**: solo el asesor que **tomó** la conversación (asignada a él,
  `IN_ATTENTION`); tomar no requiere ticket. Se puede tomar `PENDING_ADVISOR` y también
  `BOT_ATTENDING` sin asesor (intervención proactiva); tomarla apaga el bot. Toma atómica (AC-005).
- **D-023 Cierre mínimo sin ticket (provisional hasta F5)**: `POST /advisor/…/close` deja la nota
  `TICKET_CLOSED`, devuelve la conversación a `BOT_ATTENDING` con bot encendido y sin asesor. No
  crea fila en Tickets; cuando exista el módulo, el cierre pasa a cerrar el ticket.
- **D-004 Contexto para IA (2026-08-28)**: **no hay resumen**. La memoria del bot son los últimos
  **20 mensajes de la última hora** (`service.context_window`). Pasada la ventana, el mensaje se
  atiende solo. `summary`/`summary_updated_at` quedan en el modelo sin uso.
- **D-005 Guardrails (2026-08-28, largo de mensaje revisado 2026-08-31)**: **500 caracteres**
  por mensaje (bajado de 2000: de sobra para el tono conversacional del chat, sin invitar a
  pegar párrafos); **10 mensajes/min** por conversación → 429 con `Retry-After` (el rechazado
  no se persiste); imágenes 5 MB, 3 por mensaje, 20 por hora, JPG/PNG/WebP. **Sin tope
  acumulativo**: con D-003 la conversación es permanente, así que un tope duro la dejaría
  inservible de por vida.
- **D-007 IA OFF en handoff (2026-08-28)**: opción simple — la IA **no se re-enciende sola**.
  Queda apagada hasta que un asesor tome y cierre el caso (D-023 la devuelve al bot). Sin
  expiración ni temporizador; si nadie atiende, el caso espera en la bandeja.
- **D-006 Triviales (2026-08-28)**: saludo/gracias sueltos y mensaje repetido (<10 min) reciben
  respuesta fija sin llamada IA (`agent/trivial.py`); el aviso de repetición sale UNA vez y
  luego silencio. El spam por volumen lo frena el rate limit de D-005.
- **D-020 Debounce (2026-08-28)**: 6 s (`AI_DEBOUNCE_SECONDS`) como `DelaySeconds` de SQS; el
  worker salta el job si hay un mensaje más nuevo y el job del último responde la ráfaga en UNA
  llamada IA. Sin estado extra.
- **D-024 Guardrails de seguridad (2026-08-28)**: intento de manipulación (jailbreak, pedir el
  prompt, cambiar el rol, autoridad falsa, etiquetas del prompt) → respuesta fija amable, **sin
  IA y sin derivar**; datos de OTROS usuarios (RF-052) → fija de privacidad, sin derivar. Capa
  de salida: cifra o enlace que no esté en la evidencia, o fuga del prompt → se descarta la
  respuesta y deriva como "sin evidencia". Todo en `agent/guardrails.py`; corre después de la
  repetición (D-006) a propósito, para que insistir no gane una fija por intento.
- **D-025 Tono (2026-08-28)**: español peruano cercano, natural; máximo **un emoji** por
  mensaje (fijos y generados), nunca junto a cifras o enlaces; sin markdown ni guiones largos
  como separador (`guardrails.tidy` limpia lo que se escape). Mensajes fijos en `agent/prompts.py`.
  **Revisada 2026-09-03 (D-030, Aaron)**: las **negritas** `**así**` sí se permiten (pocas,
  para nombres de botones o el dato clave) y el widget las renderiza; `tidy` conserva solo
  los pares cerrados y sigue quitando encabezados, guiones bajos y asteriscos sueltos. Cada
  paso de una lista va en su línea y entre bloques hay una línea en blanco: el widget dibuja
  el texto por bloques (`renderRichText`), con sangría colgante en los "1) …" y aire entre
  párrafos. Sin URLs en el texto (van como fuente, D-030).
- **D-026 Eval de prompts (2026-08-28)**: golden set en `tests/golden/intents.jsonl`; en CI solo
  la parte determinista (`tests/test_golden_intents.py`). La eval real contra Gemini es manual:
  `python -m scripts.eval_intents` (~1 centavo) y exige ≥ 95% para mergear un cambio de prompt.
- **D-027 Tope de ejecuciones de IA (revisada e IMPLEMENTADA 2026-09-01; original
  2026-08-31)**: **anónimo 10/hora y 20/día**, contados por sesión **y** por `hash(IP)` (se
  agota la primera); **autenticado el doble (20/hora, 40/día)** por `user_id` (no por IP: es
  preciso y no se comparte — CGNAT hace que usuarios legítimos compartan IP); **con asesor no
  consume** (no hay llamada a modelo). Cuenta el **mensaje que llamó a un modelo**, no el
  mensaje a secas: triviales, guardrails, reglas y ofrecer botones de flujo (D-028) no gastan.
  Al agotarse, respuesta fija (gratis): al anónimo lo invita a **crear cuenta / iniciar
  sesión**; al autenticado, a **pedir un asesor** — ruta que sale por reglas y funciona sin
  cuota. `0 = ilimitado` **y así queda en dev por ahora** (decisión de Aaron 2026-09-01).
  Código: `agent/quota.py`, tabla `RateLimits` (PK `USER#`/`SESSION#`/`IP#`, SK ventana
  `H#`/`D#`, TTL 48 h — esquema duplicado en stack **y** `local_setup.py`), la IP viaja
  **hasheada** (HMAC, `IP_HASH_SECRET`) en el `AIJob`; compuertas en `workers/ai_worker.py`.
  Tests en `tests/test_quota.py`. Complementa a D-005 (por minuto y por conversación): esto
  frena el costo acumulado de un mismo actor.

- **D-028 Flujos guiados con quick replies (2026-09-01)**: máquina de estados **liviana** en
  la fila de Conversations (`active_flow`/`flow_step`/`flow_slots`/`flow_version`/
  `flow_expires_at`, 24 h de vigencia), botones como **eventos estructurados** en la metadata
  del mensaje (el servidor valida acción/valor/versión contra el paso vigente — editar el
  HTML no inventa acciones) y **consulta canónica** al RAG al resolver el paso. Motivo: "En
  Vivo" a secas recupera 0 resultados sobre el umbral; la canónica, 4. Nada de LangGraph (el
  worker ya orquesta; se reevalúa con flujos largos/ciclos/tools). **Los 5
  flujos activos** (F-PART y, desde 2026-09-01, F-CONS/F-LIVE/F-NEGO/F-HAB); las 16
  consultas canónicas verificadas contra el índice real.
  Detectar/ofrecer botones no llama a ningún modelo. **Mapeo completo del corpus (22
  artículos, 111 preguntas) y las respuestas de diseño: [MAPEO.md](docs/MAPEO.md).** Código:
  `agent/flows.py` (definiciones puras), composición en `workers/ai_worker.py`, transición
  atómica en `conversations/repository.py`, render en `widget/subastin.js`.

- **D-029 Casos y handoff con formulario (2026-09-02, Aaron)** — ⚠️ **la parte anónima
  (formulario con nombre/correo, handoff en el sitio, `CLOSED` de la anónima, tope de
  handoffs por IP) quedó SUPERADA por D-031 el 2026-09-05; se conserva como historia**:
  revisa D-002/D-003/D-017/D-019/D-023 tras estudiar el modelo de Intercom y Zendesk (varias conversaciones por
  persona; el ticket es la conversación escalada). **Autenticado**: un hilo permanente con el
  bot (`kind=THREAD`, id determinista: D-003 sigue) y hasta **5 casos abiertos**
  (`kind=CASE`, `MAX_OPEN_CASES_PER_USER`) creados por el **formulario de asesor** (asunto +
  detalle; correo solo si el JWT de VMC no lo trajo). El caso nace `PENDING_ADVISOR` con el
  bot apagado y trae la nota `CASE_OPENED`, el mensaje `FORM_RESPONSE` (valores + transcripción
  de los últimos 20 mensajes del hilo, para el asesor) y la confirmación fija; el hilo sigue
  con el bot **encendido** y una nota `CASE_OPENED` que enlaza al caso — pedir asesor ya no
  bloquea al bot. **Anónimo**: **una** conversación por sesión (D-002/D-018 siguen; nada en
  localStorage, decisión de Aaron); puede pedir asesor dejando **nombre y correo
  obligatorios, teléfono opcional** (RF-003 vuelve a tener efecto): su conversación se deriva
  **en el sitio** y el bot lo invita a crear cuenta en VMC. Seguridad del anónimo: la fila y
  sus mensajes llevan **TTL** (`ANONYMOUS_CONVERSATION_TTL_DAYS`, 30, DynamoDB borra solo),
  tope de handoffs por IP hasheada y día (`ANON_HANDOFFS_PER_IP_PER_DAY`, **0 en dev** como
  D-027; 5 en stage/prod), contacto validado en el servidor y jamás en logs, solo un handoff
  por conversación (409 después). Pedir asesor (regla o modelo) y "FAQ sin evidencia" ya
  **no derivan solos**: el bot **ofrece la tarjeta** (`metadata.interaction.type =
  HANDOFF_FORM`, mismo mecanismo que D-028, campos según el usuario) y sigue atendiendo;
  deriva `POST /chat/conversations/{id}/handoff` al enviarla (422 con `field`, 409 si no
  procede o hay tope, 429 por IP). **Cierre**: un caso o la conversación anónima quedan
  `CLOSED` (`closed_by`, solo lectura: mensaje → 409, nota `CONVERSATION_CLOSED`); el hilo del
  autenticado sigue volviendo al bot con `TICKET_CLOSED` (D-023). Sin autocierre: D-007 se
  mantiene. **Widget**: pestaña "Mensajes" = lista (hilo + casos con estado), tarjeta de
  formulario, barra de conversación cerrada ("Nueva conversación" / "Volver a Subastín"),
  historial desde los últimos N con "ver anteriores", y sondeo por estado (TD-001). **El
  ticket sigue siendo D-008**: el caso ES la conversación escalada; `Tickets` queda para F5
  solo si hace falta trazabilidad aparte del chat. Sin esquema nuevo en DynamoDB (GSI1 sirve
  para listar hilo + casos). Código: `conversations/forms.py` (puro, lo comparten worker y
  API), `service.request_handoff`/`list_conversations`/`owns`/`close_case`,
  `repository.create_conversation_with_messages`/`close_conversation`/`list_open_cases`,
  `api/routers/chat.py`, `workers/ai_worker._offer_handoff_form`. Tests:
  `tests/test_chat_cases.py`, `tests/test_forms.py`.
  **Revisión del 2026-09-02 (Aaron), tras ver el flujo real en la consola de dev:** cuando el
  bot se queda **sin evidencia** ya no publica el formulario de una — **pregunta** "¿quieres
  que te conecte con un asesor?" con botones sí/no (flujo `HANDOFF_CONFIRM` en `agent/flows.py`,
  misma maquinaria de D-028) y el formulario sale solo con el "sí". Cuando el usuario **pide**
  un asesor (intent ADVISOR) el formulario sigue saliendo directo: volver a preguntárselo a
  quien acaba de pedirlo es un turno de más. La confirmación **vale solo para el turno
  siguiente**: si el usuario la ignora y pregunta otra cosa, se descarta (a diferencia de un
  flujo del corpus, que espera 24 h) — un "sí" de mañana no puede derivar por un tema olvidado.

- **D-030 Respuesta completa por pregunta, estado de cuenta conocido, fuentes como chip y
  preguntas hermanas (2026-09-03, Aaron; cierra TD-009)**. El redactor ya **no dosifica**:
  "un paso a la vez" venía del proyecto de WhatsApp y en una burbuja web cabe entera la
  pregunta del corpus (mediana 76 palabras, máximo 208). **Medido en la consola** sobre una
  conversación real del 03/09: "¿Cómo me registro?" costó **4 llamadas** al redactor (una por
  cada "sí", ~1.900 tokens de entrada por 25–80 de salida; $0.0128 y 43 s de espera
  acumulada) donde una completa cuesta ~$0.004 — la entrada es el 93 % del costo de cada
  llamada, así que partir una respuesta en N turnos la multiplica por N. Y "¿persona
  jurídica?" se guardó la advertencia de la factura para un turno siguiente: ahora **las
  advertencias del contexto se dicen siempre**. La unidad es la **pregunta**, no el artículo
  (mediana 435 palabras, hasta 13 preguntas de intenciones distintas: sería un muro).
  El bot **no cierra preguntando si continuar**. **Estado de cuenta**: lo sabe la sesión
  (JWT de VMC o anónimo) y viaja al prompt en `<usuario>` (`prompts.WRITER_USER_*`, al final
  para no romper el prefijo cacheable): autenticado = tiene cuenta; anónimo = se **asume sin
  cuenta**, neutro como el Centro de Ayuda; el bot **nunca pregunta** "¿ya tienes cuenta?".
  **Fuentes**: el enlace ya no va en el texto (el prompt lo prohíbe y `Fragment.as_context`
  ya no pega "(Fuente: url)"); viaja en `metadata.sources` y el widget lo dibuja como **chip**
  bajo la burbuja, determinista desde la evidencia (RF-019 sin que el modelo escriba URLs).
  **Preguntas hermanas**: bajo cada respuesta con evidencia, hasta 3 botones con las OTRAS
  preguntas del mismo artículo (`metadata.interaction.type = RELATED_QUESTIONS`, **sin
  estado ni `flow_version`**); el clic manda la pregunta canónica al RAG **sin clasificador**
  (`related:model` en AIUsage) y se valida contra la metadata del **último mensaje del bot**,
  nunca contra el payload; un clic sobre botones viejos se degrada a texto. **Franja del
  visitante** en el hilo del widget ("inicia sesión para guardar tu conversación…"): parte de
  la UI, no un mensaje, una vez por pestaña (sessionStorage; nada en localStorage) y con un
  texto que promete solo lo que hoy es verdad. `agent/followups.py` queda como **red de
  seguridad** para continuaciones espontáneas ("y luego?"). Código: `agent/related.py`
  (puro), `agent/prompts.py`, `agent/writer.py` (`user_state`), `workers/ai_worker.py`
  (`ai.related.click`), `api/routers/chat.py` (`flow_version` opcional),
  `widget/subastin.js`. Tests: `tests/test_agent_related.py`,
  `tests/test_ai_worker_related.py`. **Pendiente de medir en stage**: `cached_tokens` (las 14
  filas locales traen 0: el prefijo de ~1.000 tokens no se está cacheando; un caché explícito
  recortaría cerca de la mitad de la entrada) y la tasa de clic en hermanas.
  **Ajustes tras la primera prueba real (mismo día, Aaron)**: (1) la pregunta **respondida**
  se detecta por **parecido con la consulta** (Jaccard de raíces de 6 letras, sin
  stopwords; `related.answered_fragment`), no por mejor score — con "Hola como me registro"
  el índice puso persona jurídica primero y el botón repetía "¿Cómo me registro?"; (2) el
  RAG conserva los hits **más allá de `top_k`** en `RagResult.overflow` (y `candidates` =
  todo lo que trajo el índice): en la segunda prueba los 4 primeros hits ya superaban el
  umbral y persona jurídica era el quinto, que se tiraba con el lookahead — `all_fragments`
  NO lo incluye, para que en la consola "descartado" siga siendo "bajo el umbral"; (3) la
  fuente se dibuja como línea "Fuente: <título subrayado>" bajo la burbuja, con puntos
  suspensivos si no cabe y el título completo al pasar el mouse — se muestra el título del
  artículo, nunca la URL, así que un enlace largo no rompe nada; (4) negritas y ritmo de
  lista en el texto (ver D-025 revisada); (5) **el asesor NO se ofrece por contexto**: se
  probó un botón "Contactar con un asesor" cuando la respuesta o su evidencia decían
  "contáctanos", y salió en "¿cómo me registro?" porque lo decía un fragmento vecino del
  artículo. En su lugar se puso un **badge permanente "Asesor humano"** junto al emoji del
  compositor (decisión de Aaron; **retirado por D-031 el 2026-09-06**: hoy el asesor se
  sugiere como último mensaje sugerido bajo cada respuesta, sin ningún botón en la UI). El
  badge pedía la tarjeta a `GET /chat/conversations/{id}/handoff/form`
  (misma spec que ofrece el bot, `service.handoff_form_for`; 409 con la misma regla que
  POST /handoff, `service.handoff_allowed`) y la muestra en el hilo **sin mensaje, sin bot y
  sin modelo**; el envío sigue siendo POST /handoff. **Formulario rediseñado** (tercera
  ronda, mismo día): a todo el ancho del hilo, cabeceras "Datos de contacto · 1/2" y "Motivo
  de la consulta" (las preguntas "¿Con quién hablamos?" sonaban informales), botón final
  **"Contactar"** (`forms.handoff_form_spec`, antes "Enviar al asesor"), una **x** que lo
  cierra, y **validación al intentar avanzar**: sin asteriscos de entrada; al pulsar Siguiente
  con obligatorios vacíos, TODOS los que falten ganan a la vez asterisco y "Falta llenar este
  campo", que se van al escribir. **Transición con movimiento** (Web Animations sobre el DOM
  vivo, porque `render()` reemplaza el árbol entero — una clase CSS en un nodo que se
  descarta no anima nada): al aparecer un formulario, `render()` primero desvanece los
  botones de pregunta y **pliega el compositor** (su altura baja a cero, así el hilo crece y
  el formulario "empuja") sobre el DOM actual, pospone cualquier otro render mientras dura
  (`formEntering`) y recién entonces dibuja; al cerrarlo o contactar, el compositor **vuelve
  subiendo** (`expandComposer` en el frame siguiente al montaje) y los botones reaparecen con
  fade. Mientras el formulario está a la vista no hay compositor ni botones de pregunta. Lo
  escrito se conserva en `formDraft` si se vuelve a abrir. **Mensaje nuevo leído desde
  arriba** (pedido de Aaron): al llegar una fila del bot o del asesor, la vista se desliza
  suave hasta alinear su **inicio** con el borde superior del hilo, en vez de saltar al
  final; lo propio y la primera apertura siguen aterrizando abajo, y los eventos de scroll de
  ese deslizamiento no cuentan como "el usuario subió a leer" (`autoScrollUntil`).

- **D-031 Anónimo = solo FAQ y solo el bot; el asesor se llega SOLO por la conversación
  (2026-09-05/06, Aaron; revisa la parte anónima de D-029 y el badge de D-030, y vuelve a
  D-002)**. El sistema se plantea **sin pensar en el anónimo**: la única diferencia está en
  el momento de derivar. **Visitante**: **una conversación por pestaña** (`sessionStorage`,
  D-018; la fila y sus mensajes siguen con TTL) y **solo FAQ**: sin formulario de contacto,
  sin handoff en el sitio, sin `CLOSED`, sin tope de handoffs por IP
  (`ANON_HANDOFFS_PER_IP_PER_DAY` eliminado) y **ningún asesor la toma**: `POST
  /advisor/…/take` responde 409 (`service.AnonymousConversation`), tampoco por intervención
  proactiva (D-022); como nunca pasa a `PENDING_ADVISOR`, tampoco aparece en la bandeja.
  Cuando pide asesor, o dice que sí a "¿deseas contactar a un asesor?", o agota la cuota
  (D-027), recibe un mensaje amable que lo manda a **iniciar sesión** en VMC con el botón
  **"Iniciar sesión"** (`metadata.interaction.type = LINKS`, `{label, url}`; el widget lo
  dibuja como enlace con pinta de botón, solo `http(s)`). La URL es un **mock**
  (`VMC_LOGIN_URL`, default `https://www.vmcsubastas.com/login`) hasta que VMC confirme la
  real, y viaja también en `POST /chat/sessions` (`links.login`) para la franja del
  visitante. **Sin botón de asesor en la UI** (el badge "Asesor humano" de D-030 y
  `GET /handoff/form` desaparecen): el agente **solo sugiere** al asesor dentro de la
  conversación: (a) bajo toda respuesta con evidencia, el **último mensaje sugerido** es
  siempre **"Contactar asesor"** (`related.ADVISOR_OPTION_LABEL`, `kind: handoff`, sin
  `query`): el clic se reconoce **por estructura** (`related.is_advisor_click`, el `value`
  del evento contra el último mensaje del bot) y va directo a `_offer_handoff_form` **sin
  clasificador ni modelo**; (b) sin evidencia, el bot pregunta "¿Deseas contactar a un
  asesor del equipo?" (flujo `HANDOFF_CONFIRM`, **igual** para anónimo y autenticado; los
  botones sí/no son la respuesta a ESA pregunta, no un botón de asesor, y se entienden
  también escritos); (c) "quiero un asesor" escrito de la nada sí pasa por el orquestador
  (reglas o modelo) y termina en el mismo sitio. Lo único que distingue al anónimo es la
  respuesta final (`_offer_handoff_form`): iniciar sesión en vez del formulario.
  **REVISADA el 2026-09-08 (Aaron): bajo una respuesta CON evidencia ya no se ofrece asesor.**
  (a) El redactor no lo nombra — la regla 8 de `WRITER_SYSTEM` decía "si el contexto manda a
  contactarnos, di que puede pedir un asesor con el botón Contactar asesor" y salía en "¿cómo me
  registro?" porque lo decía un fragmento vecino; (b) `related.related_metadata` ya **no** cierra
  la lista con "Contactar asesor" (y sin preguntas hermanas devuelve `{}`, sin botones). Motivo
  de fondo: el bot existe para QUITAR carga a los asesores, y ofrecer una persona en cada
  respuesta empuja al revés. Quedan dos vías, las dos intencionales: el usuario lo pide (reglas
  o modelo) o el bot **no tiene evidencia** y pregunta sí/no (`HANDOFF_CONFIRM`). Cuando el bot
  resuelve no ofrece a nadie; cuando no puede, lo ofrece él. `related.is_advisor_click` y sus
  constantes **se conservan**: las respuestas ya guardadas en DynamoDB traen ese botón y su clic
  debe seguir abriendo el formulario en vez de degradarse a texto. El lado
  autenticado (formulario → caso → ticket) queda como está: Aaron lo revisará aparte. **Formulario del
  autenticado en un solo paso** (asunto, detalle y correo si el JWT no lo trajo; el "dos
  pasos" era por los cinco campos del anónimo) y **solo lo ofrece el bot**;
  `contact_name/email/phone` desaparecen de Conversations, Tickets, la API del asesor y el
  frontend. RF-003 / AC-003 / RB-002 vuelven a quedar **sin efecto**. Código:
  `agent/related.py` (`related_metadata` cierra con el asesor), `conversations/forms.py`,
  `service.handoff_allowed`/`request_handoff`/`take_conversation`,
  `workers/ai_worker._reply_login`, `agent/prompts.ANON_LOGIN_RESPONSE`,
  `api/routers/chat.py` (`SessionLinks`), `widget/subastin.js` (`renderLinks`,
  `renderAnonBanner`, `renderRelatedQuestions` con `kind: handoff`). Tests:
  `tests/test_chat_cases.py` (AC-H1), `tests/test_ai_worker.py`,
  `tests/test_ai_worker_related.py` (clic del asesor), `tests/test_advisor_api.py` (toma
  del anónimo), `tests/test_forms.py`.

- **D-010 Campos de usuario que llegan de VMC (2026-09-07, Aaron)**: el JWT de identidad trae
  `sub` (texto) y `user_id` (número) con el id VMC, `email` y **`cuu`** — el código que la
  plataforma le muestra a la persona (`ZEEJ7K`) y que dice por teléfono. Se guardan **CUU,
  user_id y correo** en `Conversation` y en `Ticket` (`user_cuu`), y el asesor los ve en la
  ficha de la conversación. **El nombre NO viene del JWT** (el payload real no lo manda): es
  algo que el KAM asigna en la conversación si quiere, así que `user_name` sigue existiendo
  pero vacío mientras VMC no mande `name`. El CUU es **solo para mostrar**: no hay GSI ni
  búsqueda por él, y nunca es credencial — es visible para el usuario y no prueba nada; quien
  identifica es `user_id`, que sale del JWT firmado. **Sin cambio de esquema en DynamoDB**:
  son atributos que no son clave, así que ni el stack ni `local_setup.py` se tocan. Código:
  `core/auth.py` (`VmcIdentity.cuu`, `_clean_id` acepta el claim numérico),
  `conversations/{models,service,repository}.py`, `tickets/{models,service}.py`,
  `api/schemas.py`, `frontend/src/lib/types.ts` y la ficha del asesor. Contrato para VMC en
  `widget/README.md`. Tests: `tests/test_core_auth.py`, `tests/test_chat_conversations.py`,
  `tests/test_tickets_api.py`.

## Decisiones de NEGOCIO abiertas (D-xxx) — responsables: Silvana + Julio

Detalle en [REQUERIMENTS.md](docs/REQUERIMENTS.md) §6 y PLAN.md §9.

| ID | Tema | Prio | Bloquea |
|---|---|---|---|
| D-008 | Taxonomía de problemas/tickets y campos | Alta | Campos definitivos y SLA por tipo. **Propuesta de Aaron IMPLEMENTADA** (2026-09-02) en `backend/tickets/taxonomy.py`: 12 `problem_type` del corpus con categoría, prioridad y datos mínimos (MAPEO.md §8). El módulo Tickets ya corre con ella; cerrar la decisión = editar ESE archivo. **Sigue abierta**: la validan Silvana + Julio contra los motivos reales de Intercom |
| D-009 | Tags de negocio | Media | Tickets |
| D-011 | Contrato HERALD (endpoints, auth, filtros) | Alta | F4 |
| D-012 | Fallback cuando HERALD caído | Media | F4 |
| D-013 | Métricas exactas del dashboard | Media | F7 |
| D-014 | Retención (¿6 meses?) conversaciones/imágenes | Alta | TTL, S3 lifecycle |
| D-015 | Procesamiento de imágenes para IA (modelo, resize) | Media | F6 |
| D-016 | Canal Slack y formato de notificación | Baja | worker-notify |

D-001…D-007, D-010, D-017, D-019, D-020, D-021…D-031 **cerradas** (arriba); D-018 provisional.
D-027 quedó **implementada** el 2026-09-01 (T-09 hecho) con los topes **apagados en dev**
(`AI_QUOTA_* = 0`); en stage/prod se encienden por variables de entorno.

## Decisiones TÉCNICAS abiertas (TD-xxx)

| ID | Tema | Recomendación actual |
|---|---|---|
| TD-001 | Entrega en tiempo real: polling vs API Gateway WebSocket | **Sigue polling** (revisado 2026-09-01, Aaron): `widget/subastin.js` sondea 2,5 s abierto / 15 s cerrado, pausa con pestaña oculta. Webhook no es opción (el navegador no tiene URL pública) y SSE tampoco (HTTP API + Lambda no hace streaming, T1/T2), así que la alternativa real es una **API WebSocket aparte**. **No es un problema de latencia**: el piso lo pone el debounce de 6 s de D-020, y el polling solo agrega ~1,25 s de media sobre un presupuesto de 10 s (RNF-001). El argumento es **costo**: cada poll = 1 request de API Gateway + 1 Lambda + 1 query DynamoDB, o sea 1.440 req/hora por usuario con el chat abierto y 240 con la página cargada. Construirlo cuesta: API nueva en CDK, auth en `$connect` con el token de D-001, tabla de conexiones (duplicada en stack **y** `local_setup.py`), push desde `ai_worker`/`advisor` con `post_to_connection` + IAM, reconexión con backoff, **y el polling se queda igual de fallback** (redes que bloquean WS). Además rompería T5 si localstack no cubre WebSocket. **Polling adaptativo implementado el 2026-09-02** (`widget/subastin.js`): cadencia por estado —2 s esperando al bot, 5 s con asesor, 15 s en reposo, 60 s con el panel cerrado solo si hay casos abiertos (una llamada a la lista), nada en los demás casos (el anónimo cerrado no sondea: solo FAQ, D-031)—, backoff exponencial con jitter ante errores, arranque perezoso del anónimo (sin sesión hasta abrir el chat: antes cada pestaña de VMC creaba una fila) y el estado de la conversación viaja en cada sondeo. Revisar WebSocket con números de tráfico reales de producción |
| TD-002 | Haiku vía API Anthropic directa vs Amazon Bedrock | Preguntar al equipo AWS si Bedrock está habilitado (PLAN §6.8); sin respuesta aún |
| TD-003 | Hosting frontend: Vercel vs Amplify | Sin recomendación aún; fuera del stack CDK en ambos casos |
| TD-004 | Cuentas AWS separadas stage/prod vs una sola | Separadas si el equipo AWS lo permite |
| TD-005 | `PythonFunction` (bundling) vs `DockerImageFunction` | PythonFunction mientras deps < 250 MB descomprimido |
| TD-007 | Dominio custom para la API + DNS/ACM | No bloquea MVP; URL default de API Gateway mientras tanto |
| TD-009 | Procesos multi-paso: ¿reglas de texto, flujo con estado, o acotar el prompt? | **Cerrada el 2026-09-03 con D-030** (opción b + botones sin estado): el redactor responde **completa** la pregunta del corpus y no promete "el siguiente paso"; lo relacionado sale como botones de preguntas hermanas (`agent/related.py`). `agent/followups.py` queda como red de seguridad para continuaciones espontáneas. Historia y datos en la viñeta D-030 |
| TD-010 | **¿Reranker como decisor de evidencia, en lugar del umbral de e5?** | **Abierta desde 2026-09-03**, con datos en [BENCHMARK.md](docs/BENCHMARK.md) §3–4. El score de `multilingual-e5-large` comprime todo el corpus entre 0.78 y 0.88, así que **no existe un `RAG_MIN_SCORE` bueno**: 0.84 da recall 84% / rechazo 90%, y cada centésima mueve decenas de casos (0.83 → 91/55, 0.85 → 76/95). Un cross-encoder alojado en Pinecone (`bge-reranker-v2-m3`, `pc.inference.rerank`, mismo proveedor, sin Gemini) puntúa "¿este fragmento responde la pregunta?" y separa de verdad: negativos en 0.00–0.02, positivos en 0.6–0.99; con umbral **0.10** da **89% / 95%** sobre los mismos 121 casos, y "¿pongo RUC o DNI?" (que el corpus no responde) cae a 0.001. **Lo que ni el reranker arregla**: sinónimos del rubro (garantía = consignación, me cobran = comisión) y erratas en la palabra clave (komision); eso es del **corpus** — preguntas alternativas por fragmento en la ingesta y corrección ortográfica contra el vocabulario — no del decisor. **Recomendación**: reranker ≥ 0.10 como decisor, e5 como prefiltro de 8 candidatos con piso flojo (≈ 0.75); antes, verificar cuota del reranker en el plan de Pinecone y latencia desde Lambda. Hasta decidirlo, `--rerank` en `scripts/eval_retrieval.py` es solo medición |
| TD-008 | ¿Gemini también clasifica, o vuelve Haiku (T9)? | **Gemini provisional** desde 2026-08-27; **modelos recalibrados 2026-09-01** contra la página oficial de precios: `gemini-3.5-flash-lite` clasifica ($0.30/$2.50 por 1M; respaldo `3.1-flash-lite`) y `gemini-3.6-flash` redacta ($1.50/$7.50; respaldo `3.5-flash` a $1.50/$9.00). Se abandonó `3.7-flash`: existe en la API pero NO figura en la tabla de precios (preview sin tarifa) y con key gratuita rechazaba sostenido ("high demand") — en la práctica todo caía al respaldo con un costo estimado inventado. Un solo proveedor = una credencial y una integración menos. Se decide con el golden set de intents: si el routing no alcanza, el tier `FAST` de `core/llm.py` vuelve a Haiku (y ahí sí aplica TD-002) |

TD-006 **cerrada** (2026-08-24): la v0 (WhatsApp+Gemini) se eliminó del repo; backup en
`../chatbot-ai-vmc-v0-backup.zip`.
