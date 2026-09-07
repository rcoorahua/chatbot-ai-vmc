# Subastín — plataforma de atención de VMC

Subastín reemplaza a Intercom como la plataforma propia de atención al cliente de **VMC**
(subastas de vehículos). Es un **chat embebido en la web de VMC** donde una IA resuelve lo
resoluble y, cuando no debe o no puede, deriva a un **asesor humano** que atiende desde su
propia bandeja.

- **Cómo desplegarlo en AWS:** [DEPLOYMENT.md](DEPLOYMENT.md)
- **Qué tiene que hacer el producto:** [docs/REQUERIMENTS.md](docs/REQUERIMENTS.md)
- **Cómo está construido:** [docs/PLAN.md](docs/PLAN.md)

---

## 1. Qué hace

| Quién | Qué obtiene |
|---|---|
| **Visitante** (sin sesión) | Abre el chat sin login ni datos. Solo preguntas frecuentes, y su conversación dura lo que la pestaña. Lo atiende únicamente el bot: para hablar con una persona tiene que iniciar sesión en VMC, y el bot se lo dice con un botón |
| **Usuario con sesión en VMC** | Lo mismo, más una **conversación permanente** ligada a su identidad de VMC y hasta 5 casos abiertos con un asesor |
| **Asesor / KAM** | Bandeja de pendientes, "Tomar conversación" (sin que dos asesores tomen la misma), hilo con los datos del usuario, respuesta, tickets y cierre |

**Qué pasa cuando alguien escribe:** se clasifica la intención → si es una pregunta frecuente se
busca la respuesta en el Centro de Ayuda (Pinecone) → un modelo redacta la respuesta **usando solo
esa evidencia**. Si no hay evidencia o el usuario pide una persona, **no se inventa nada**: el bot
ofrece contactar a un asesor, y al aceptar se abre un caso con su ticket y el bot se apaga hasta
que alguien lo atienda.

Reglas que no se negocian: los datos de VMC son de **solo lectura**, el bot nunca expone
información de otros usuarios, y la identidad del usuario jamás se cree por lo que diga el
navegador — siempre viene firmada.

---

## 2. Qué hay en cada carpeta

| Carpeta | Qué es | Se despliega |
|---|---|---|
| **`backend/`** | Todo el código Python: la API (FastAPI) y los dos workers. Es un monolito modular con las dependencias en una sola dirección: entradas (`api/`, `workers/`) → dominio (`conversations/`, `tickets/`, `advisors/`) → integraciones (`agent/`, `catalog/`, `images/`, `notifications/`) → `core/`. La regla completa está en `backend/__init__.py` y una prueba la hace cumplir | CDK → 3 Lambdas |
| **`infra/`** | La infraestructura como código (CDK v2 en Python): tablas, colas, Lambdas, API Gateway, Cognito, S3, secretos. Un stack por entorno | Es el que despliega |
| **`widget/`** | El chat que se embebe en la web de VMC. `subastin.js` es un archivo **generado**: se edita `widget/src/*.js` y se regenera con `node widget/build.mjs`. `test.html` simula la página de VMC para probarlo | Archivo estático (CDN de VMC) |
| **`frontend/`** | La app del asesor y el dashboard (Next.js 16, TypeScript, Tailwind) | Fuera de CDK (Vercel o Amplify) |
| **`scripts/`** | Utilidades de línea de comandos: crear tablas y colas en local, cargar datos de prueba, subir el Centro de Ayuda a Pinecone, correr el bot en local y medir su calidad | No |
| **`tests/`** | La suite de pruebas (1.100). Corren contra DynamoDB y SQS **reales** en Docker, no contra simulaciones | No |
| **`docs/`** | Toda la documentación del proyecto (ver §6) | No |
| **`.github/workflows/`** | `ci.yml` (lo que corre en cada PR) y `deploy.yml` (el despliegue, aún apagado) | — |
| **`.claude/`** | 12 skills de metodología y un hook de seguridad, para trabajar con Claude Code | No |

En la raíz quedan solo cuatro documentos: este `README.md`, [DEPLOYMENT.md](DEPLOYMENT.md),
[CLAUDE.md](CLAUDE.md) (el registro vivo de decisiones) y [DETAILS.md](DETAILS.md) (auditoría
técnica).

---

## 3. Cómo está construido

```
widget en vmcsubastas.com          app del asesor (Next.js)
        │                                   │
        │ /chat/*                           │ /advisor/*, /dashboard/*
        │ (identidad firmada por VMC)       │ (login de Cognito)
        ▼                                   ▼
                 API Gateway HTTP API
                          │
                          ▼
                 Lambda `api` (FastAPI)  ── encola y responde al instante ──►  SQS
                          │                                                     │
                          ▼                                                     ▼
        DynamoDB · S3 · Secrets Manager                          Lambda `worker-ai`
                                                                  (Gemini + Pinecone)
```

La respuesta del bot es **asíncrona**: la API contesta enseguida y el widget pregunta cada pocos
segundos si ya está lista. Así la latencia de los modelos no bloquea la petición del usuario, y
un fallo se reintenta solo.

Todo el detalle de servicios, entornos y despliegue está en **[DEPLOYMENT.md](DEPLOYMENT.md)**.

---

## 4. Correrlo en tu máquina

No hace falta cuenta de AWS: en local todo corre en Docker (DynamoDB y SQS de mentira, pero
reales para el código).

### Qué necesitas instalado

| | Versión | Para qué |
|---|---|---|
| **Docker Desktop** | cualquiera reciente | La base de datos y las colas locales |
| **Python** | 3.12 o más | El backend y las pruebas |
| **Node** | 22 | El frontend y el widget |
| **Git** | — | — |

Opcionales: **AWS CLI** (para mirar los datos a mano) y una **`GEMINI_API_KEY`** +
**`PINECONE_API_KEY`** si quieres que el bot responda de verdad; sin ellas todo lo demás funciona.

### Instalación (una sola vez)

```powershell
git clone https://github.com/rcoorahua/chatbot-ai-vmc.git
cd chatbot-ai-vmc
git config core.hooksPath .githooks     # impide pushear directo a main/develop

python -m venv .venv
.venv\Scripts\Activate.ps1               # macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"

Copy-Item .env.example .env              # sirve tal cual; ver la nota de abajo
cd frontend; npm install; cd ..
```

> **Sobre el `.env`:** copiado tal cual ya funciona. Para que el chat abra sesión necesita
> `VMC_IDENTITY_SECRET` y `SESSION_SIGNING_KEY` (en dev sirve cualquier texto), y para que el bot
> conteste, `GEMINI_API_KEY` y `PINECONE_API_KEY`. Las pruebas no lo necesitan.

### Arrancar (cada día)

```powershell
docker compose up -d              # DynamoDB (:8001) + LocalStack SQS/S3 (:4566)
python -m scripts.local_setup     # crea las 6 tablas, las 2 colas y el bucket
python -m scripts.seed_data       # datos de prueba

uvicorn backend.api.main:app --reload --port 8000    # la API
python -m scripts.run_ai_worker                      # en otra terminal: el bot
cd widget; python -m http.server 8080                # en otra: el widget
cd frontend; npm run dev                             # en otra: la app del asesor
```

| Qué | Dónde |
|---|---|
| API + documentación interactiva | <http://localhost:8000/docs> |
| Widget (simula la página de VMC) | <http://localhost:8080/test.html> |
| App del asesor | <http://localhost:3000> |

Dos advertencias que ahorran tiempo:

- **DynamoDB local vive en memoria**: cada vez que reinicies los contenedores hay que volver a
  correr `local_setup` y `seed_data`. Para limpiar sin reiniciar Docker:
  `python -m scripts.reset_local`.
- **El worker de IA no se recarga solo.** `uvicorn --reload` sí recoge los cambios de la API,
  pero si tocas `agent/`, `workers/` o `conversations/` hay que **reiniciar el worker**; si no,
  te responde el proceso viejo y parece que tu arreglo no funcionó.

### Comprobar que todo está bien

```powershell
python -m pytest -q               # 1.100 pruebas (necesita Docker arriba)
python -m ruff check .            # lint del backend
node widget/build.mjs --check     # el widget generado está al día
node --check widget/subastin.js   # sintaxis del widget
cd frontend; npm run lint; npm run build
cd infra; npx -y aws-cdk@2 synth -c stage=stage    # valida la infra sin desplegar
```

Es exactamente lo que corre el CI. Si esto pasa en tu máquina, el PR pasa.

### Si algo falla

| Síntoma | Qué hacer |
|---|---|
| `ModuleNotFoundError` | Activa el entorno: `.venv\Scripts\Activate.ps1` |
| Las pruebas no encuentran las tablas | `docker compose up -d` y vuelve a correr `scripts.local_setup` |
| Errores de Docker al correr CDK | Docker Desktop no está corriendo |
| El puerto 8000 está ocupado | `Get-NetTCPConnection -LocalPort 8000 \| Select OwningProcess`, luego `Stop-Process -Id <id> -Force` |
| Te rechaza el push a `develop` o `main` | Es lo correcto: hay que abrir un pull request |
| El bot dice que no está disponible | La clave gratuita de Gemini tiene pocas peticiones por ventana; espera un rato |

<details>
<summary><b>Mirar los datos a mano con el AWS CLI</b> (opcional)</summary>

Configura un perfil una vez, apuntando a los contenedores:

```powershell
aws configure set profile.subastin-local.region us-east-1
aws configure set profile.subastin-local.aws_access_key_id local
aws configure set profile.subastin-local.aws_secret_access_key local
aws configure set profile.subastin-local.services subastin-local-endpoints
```

Y añade al final de `~/.aws/config`:

```ini
[services subastin-local-endpoints]
dynamodb =
  endpoint_url = http://localhost:8001
sqs =
  endpoint_url = http://localhost:4566
s3 =
  endpoint_url = http://localhost:4566
```

Luego, por ejemplo:

```powershell
# Todas las conversaciones
aws --profile subastin-local dynamodb scan --table-name subastin-dev-conversations --query 'Items[].[conversation_id.S,status.S,user_cuu.S]' --output table

# El hilo de una conversación, en orden
aws --profile subastin-local dynamodb query --table-name subastin-dev-messages --key-condition-expression "conversation_id = :c" --expression-attribute-values '{\"c\":{\"S\":\"conv_002\"}}' --query 'Items[].[created_at.S,sender_type.S,content.S]' --output table

# La bandeja del asesor (índice gsi2_inbox; `status` es palabra reservada, de ahí el alias #s)
aws --profile subastin-local dynamodb query --table-name subastin-dev-conversations --index-name gsi2_inbox --key-condition-expression "#s = :e" --expression-attribute-names '{\"#s\":\"status\"}' --expression-attribute-values '{\":e\":{\"S\":\"PENDING_ADVISOR\"}}' --output table
```

En macOS y Linux, quita las barras invertidas de los JSON (las necesita PowerShell, no bash).

La consola de `widget/test.html` muestra lo mismo de forma más cómoda para el día a día: por cada
mensaje, qué capa decidió, qué modelo respondió, cuántos tokens costó y cuánto tardó.

</details>

---

## 5. Cómo se trabaja y qué pasa al pushear

Ramas cortas que salen de `develop` y vuelven por pull request. Nunca se pushea directo a
`develop` ni a `main` (un hook local lo impide, y GitHub también).

```
feature/<algo> · fix/<algo>  ──PR──►  develop  ──►  stage
                                         │
                                  PR de release
                                         ▼
                                       main  ──►  prod (con aprobación manual)
```

### En cada pull request corre el CI ([ci.yml](.github/workflows/ci.yml))

Cuatro trabajos en paralelo, sin credenciales de AWS:

| Trabajo | Qué verifica |
|---|---|
| **lint** | `ruff` sobre el backend, sintaxis del widget y que `subastin.js` esté regenerado |
| **test** | Las 1.100 pruebas contra DynamoDB y LocalStack reales, levantados como servicios |
| **frontend** | `npm run lint` y `npm run build` |
| **synth** | Las pruebas de infraestructura y `cdk synth`: valida el stack sin desplegar nada |

Un push nuevo a la misma rama cancela la corrida anterior.

### Al mergear

| Rama | Qué pasa |
|---|---|
| `develop` | Despliega a **stage** |
| `main` | Muestra el `diff`, **espera aprobación** y despliega a **prod** |

> El despliegue automático está **escrito pero apagado** hasta que exista la cuenta de AWS. Lo
> que falta para encenderlo está paso a paso en [DEPLOYMENT.md](DEPLOYMENT.md) §4.

Los mensajes de commit siguen Conventional Commits y citan el requerimiento o la decisión que
cierran (`Implementa RF-018`, `Cierra D-010`).

---

## 6. Documentación

Para entender el proyecto, en este orden:

1. **[docs/REQUERIMENTS.md](docs/REQUERIMENTS.md)** — qué tiene que hacer el producto:
   requerimientos, reglas de negocio, criterios de aceptación y el modelo de datos.
2. **[docs/PLAN.md](docs/PLAN.md)** — cómo está construido: decisiones de arquitectura, rutas,
   entornos y fases.
3. **[DEPLOYMENT.md](DEPLOYMENT.md)** — qué crea el CDK, qué servicios usa y qué falta conectar
   para desplegar.
4. **[CLAUDE.md](CLAUDE.md)** — el registro vivo: qué se decidió, qué sigue abierto y por qué.
   Regla central: **nada que dependa de una decisión abierta se implementa asumiendo un valor**.
5. **[docs/BACKLOG.md](docs/BACKLOG.md)** — el trabajo en tickets tomables, con sus dependencias.

De consulta puntual: [docs/MAPEO.md](docs/MAPEO.md) (qué preguntas del Centro de Ayuda llevan
botones), [docs/TEST.md](docs/TEST.md) (prueba manual del bot),
[docs/BENCHMARK.md](docs/BENCHMARK.md) (calidad de la búsqueda, con números),
[docs/DESIGN.md](docs/DESIGN.md) y [docs/PRODUCT.md](docs/PRODUCT.md) (el panel del asesor),
[DETAILS.md](DETAILS.md) (auditoría técnica) y [widget/README.md](widget/README.md) (el contrato
de identidad que implementa VMC).

---

## 7. En qué estado está

**Funciona hoy, en local:** el chat completo con identidad de VMC, el bot respondiendo con
búsqueda en el Centro de Ayuda, los flujos guiados con botones, el formulario para contactar a un
asesor con su caso y su ticket, la bandeja del asesor con toma atómica y cierre, los topes de uso
y toda la observabilidad de costos.

**Falta:** el catálogo de vehículos (HERALD), los avisos por Slack, las imágenes, el dashboard de
métricas y conectar el login del asesor con Cognito. Cada uno espera una decisión de negocio o la
cuenta de AWS; están listados en [CLAUDE.md](CLAUDE.md) y repartidos en
[docs/BACKLOG.md](docs/BACKLOG.md).
