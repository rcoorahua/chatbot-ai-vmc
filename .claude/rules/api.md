---
paths:
  - "backend/api/**"
  - "backend/workers/**"
  - "backend/core/observability.py"
  - "backend/core/auth.py"
  - "widget/test.html"
---

# API, workers y observabilidad

- **`api/` (desde 2026-09-07)**: las excepciones de dominio se traducen a HTTP en UN solo
  sitio, `api/errors.py` (`RESPONDERS`, instalado en `main.py`); los routers llaman al
  service y dejan subir la excepción, sin `try/except`. Los modelos de salida (`*Out`,
  `ProjectionModel.from_model`, `page_cursors`) viven en `api/schemas.py`; los de entrada,
  en cada router. Ningún router importa un `repository` (lo verifica
  `tests/test_architecture.py`, junto con la regla de dependencias, `os.environ` solo en
  `core/config.py` y "lo que vive en `core` no se vuelve a definir").
- `backend/api/main.py`: `Mangum(app, lifespan="off")` — con lifespan activo la Lambda se cuelga
  en el startup. Los routers `advisor`/`dashboard` **no** validan JWT en código: lo hace el
  authorizer de Cognito en el API Gateway (T1); el backend solo lee los claims que Mangum deja en
  `request.scope["aws.event"]` (`core/auth.py`). En local `ADVISOR_DEV_AUTH=1` instala
  `api/dev_auth.py`, que verifica un JWT propio (`ADVISOR_DEV_JWT_SECRET`) y deja los claims en el
  mismo sitio; se ignora dentro de una Lambda. Por eso no hay que "pushear el infra" para probar
  `/advisor`: el stack ya trae el User Pool y el authorizer, y se despliega junto con el código.
- Los workers devuelven siempre `{"batchItemFailures": [...]}` (contrato de SQS partial batch
  response, T3) — lo verifica `tests/test_smoke.py`.
- **Observabilidad (RNF-006)**: `core/observability.py` configura el logging al importar cada
  entrada (`api/main.py`, workers). Política: dev/stage `DEBUG` con vista previa del contenido;
  prod `INFO` **sin contenido** (`content_preview` devuelve solo el largo). JSON dentro de Lambda,
  texto en local. Convención: el mensaje del log es el nombre del evento (`ai.execution`,
  `ai.handoff`, `ai.debounce.skip`…) y los datos van en `extra`; `usage.record_execution` emite
  un `ai.execution` por ejecución con las mismas claves que la fila de AIUsage. **Peticiones HTTP (2026-09-02, `api/request_log.py`)**: un `http.request`
  por petición (método, plantilla de ruta, path, estado, duración, `request_id`) y un
  `http.error` con el MOTIVO de cada rechazo — que es lo que convierte "un 404" en "un 404
  porque la conversación no existe". El nivel sigue al resultado (2xx DEBUG, 4xx WARNING, 5xx
  ERROR), así que en prod (INFO) los problemas saltan solos y el tráfico normal no. **Se
  instala AL FINAL en `api/main.py`**: `add_middleware` antepone, así que el último agregado es
  el más externo; instalado antes quedaba por dentro del authorizer de dev y sus 401 no dejaban
  rastro. **El authorizer de dev, en cambio, va ANTES que CORS (2026-09-08)**: agregado primero
  queda por DENTRO de `CORSMiddleware`, así sus 401 salen con `Access-Control-Allow-Origin`. Al
  revés, el navegador descartaba el 401 como error de CORS y `fetch` fallaba con un TypeError:
  la app del asesor decía "No se pudo conectar con el servidor" cuando lo que faltaba era el
  token (`tests/test_api_cors.py` lo fija). Nunca registra el cuerpo, la cabecera `Authorization` ni la query cruda: por ahí van
  los mensajes, el formulario de handoff y el token de sesión. La ruta
  `GET /dev/conversations/{id}/ai-usage` (`api/routers/dev.py`) alimenta la consola de
  `widget/test.html`; con `DEV_OBSERVABILITY=0` (prod) responde 404. Nunca loguear contenido
  fuera de `content_preview`. El mismo router también trae `GET /dev/tables[/{key}]` y
  `GET /dev/queues` (pestañas "Tablas"/"Cola" de `test.html`): un `scan` completo de cada tabla
  y un peek de SQS con `VisibilityTimeout=0`. Gate más estricto que `ai-usage` a propósito —
  `_solo_dev()` exige `stage == "dev"`, ni siquiera vive en stage — porque un scan expone
  mensajes de TODOS los usuarios, no solo la conversación propia.
