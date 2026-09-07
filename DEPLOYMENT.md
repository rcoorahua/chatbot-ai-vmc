# DEPLOYMENT.md — cómo está configurado el despliegue

Guía para el equipo que va a conectar este repositorio con AWS. Explica **qué crea el CDK**,
**qué servicios se usan**, **qué falta conectar** antes del primer despliegue y **cómo se
despliega**.

Fuente de verdad de arquitectura: [docs/PLAN.md](docs/PLAN.md). Este archivo es el resumen
operativo.

---

## 1. Qué se despliega y qué no

| Pieza | Dónde vive | Cómo se despliega |
|---|---|---|
| **Backend** (API + 2 workers) | `backend/` | **CDK** (`infra/`), un stack por entorno |
| **Infraestructura** (tablas, colas, buckets, auth) | `infra/` | **CDK**, el mismo stack |
| **App del asesor** (Next.js) | `frontend/` | **Fuera de CDK** — Vercel o Amplify, sin decidir (TD-003) |
| **Widget del chat** | `widget/subastin.js` | **Fuera de CDK** — un archivo estático que sirve VMC o un CDN |
| **Entorno de desarrollo** | `docker-compose.yml` | **No se despliega**: corre local con DynamoDB Local + LocalStack |

Hay **dos entornos desplegables**: `stage` y `prod`. `dev` es local y nunca toca AWS.

```
develop  ──►  stage   (despliegue automático al mergear)
main     ──►  prod    (despliegue con aprobación manual)
```

---

## 2. Servicios AWS que usa el stack

Todo es **serverless y de pago por uso**: sin servidores que administrar y sin costo fijo
mientras no haya tráfico.

| Servicio | Para qué | Detalle |
|---|---|---|
| **API Gateway (HTTP API)** | La única puerta de entrada | HTTP API v2, no REST API (más barato y suficiente). Un stage `$default` con límite global de 50 req/s (ráfaga 100) |
| **Lambda** ×3 | Todo el cómputo | `api` (FastAPI completo vía Mangum), `worker-ai` (responde el bot), `worker-notify` (Slack, aún un stub) |
| **DynamoDB** ×6 tablas | Toda la persistencia | `conversations`, `messages`, `tickets`, `advisors`, `ai-usage`, `rate-limits`. Todas *on-demand* (`PAY_PER_REQUEST`) |
| **SQS** ×2 colas + 2 DLQ | Desacoplar la IA del request HTTP | `ai-jobs` (el bot) y `notifications`. Cada una con su *dead letter queue* tras 3 intentos |
| **Cognito** | Login de los asesores | User Pool sin auto-registro: solo por invitación. El JWT lo valida el API Gateway, no el código |
| **S3** | Imágenes que manda el usuario | Bucket privado (todo acceso público bloqueado); se sirven con URLs firmadas |
| **Secrets Manager** ×2 | Credenciales | Un secreto de identidad (para la API) y uno de IA (para el worker). Ver §5 |
| **CloudWatch Logs** | Logs de las 3 Lambdas | Retención: 14 días en stage, 90 en prod |

**Servicios de terceros** (no son de AWS, hacen falta sus credenciales): **Gemini** (clasifica y
redacta), **Pinecone** (búsqueda del Centro de Ayuda), y más adelante **Slack** (avisos) y
**HERALD** (catálogo de vehículos, bloqueado por la decisión D-011).

### Cómo se conecta todo

```
Widget en vmcsubastas.com          App del asesor (Next.js, fuera de AWS)
        │                                   │
        │  /chat/*                          │  /advisor/*, /dashboard/*
        │  (JWT de VMC + token de sesión)   │  (JWT de Cognito)
        ▼                                   ▼
              API Gateway HTTP API
                       │
                       ▼
              Lambda `api`  ──── responde 202 y encola ────►  SQS ai-jobs
                       │                                          │
                       │                                          ▼
                       │                               Lambda `worker-ai`
                       │                                 │      │       │
                       │                              Gemini  Pinecone  │
                       │                                              SQS notifications
                       ▼                                                  │
              DynamoDB · S3 · Secrets Manager                   Lambda `worker-notify`
```

La respuesta del bot es **asíncrona**: la API contesta al instante y el widget consulta cada
pocos segundos si ya hay respuesta. Eso mantiene la API rápida y hace que un fallo del modelo se
reintente solo en vez de romper la petición del usuario.

---

## 3. Cómo está organizado el CDK

```
infra/
├── app.py                     # entrada: exige -c stage=stage|prod
├── config.py                  # lo que cambia entre entornos (memoria, logs, CORS, retención)
├── cdk.json                   # "app": "python app.py"
├── requirements.txt           # versiones EXACTAS de aws-cdk-lib y la alpha
├── stacks/subastin_stack.py   # todos los recursos
└── tests/                     # pruebas del stack sin desplegar (aws_cdk.assertions)
```

**Un solo stack, dos entornos.** El mismo código produce `subastin-stage` y `subastin-prod`; lo
que difiere está en `config.py`:

| | stage | prod |
|---|---|---|
| Memoria de la Lambda `api` | 512 MB | 1024 MB |
| Retención de logs | 14 días | 90 días |
| Al destruir el stack | borra los datos | **los conserva** (`RETAIN`) |
| CORS | `*` | solo `vmcsubastas.com` |
| Nivel de log | `DEBUG`, con vista previa del contenido | `INFO`, **sin** contenido de los mensajes |
| Rutas `/dev/*` (consola de pruebas) | encendidas | apagadas |

Los **límites de negocio** (500 caracteres por mensaje, 10 mensajes/minuto, cuotas de IA, umbral
del buscador…) son idénticos en los dos entornos y viven en `BUSINESS_ENV`, dentro del stack. Una
prueba los compara contra `.env.example` para que local y AWS no se separen sin que nadie avise.

**Empaquetado de las Lambdas.** Cada función se construye dentro de Docker con **solo sus
dependencias** (`backend/requirements-api.txt`, `-worker-ai.txt`, `-worker-notify.txt`), así que
la Lambda de la API no carga las librerías de IA. Por eso `cdk synth` y `cdk deploy` **necesitan
Docker corriendo**.

**Permisos.** No hay ni una política IAM escrita a mano: se usan *grants* de CDK, y cada Lambda
recibe únicamente lo que consume (por ejemplo, `worker-notify` no puede leer ningún secreto).

---

## 4. Qué falta para el primer despliegue

El código está listo; lo que falta es todo lo que depende de tener una cuenta AWS. **En este
orden:**

### 4.1 Cuenta y región

1. Decidir si `stage` y `prod` van en **cuentas separadas** o en una sola (recomendado:
   separadas; decisión TD-004).
2. Completar `account` y confirmar `region` en `infra/config.py` — hoy están en `None` y
   `us-east-1` a propósito, para no inventar valores.
3. Ejecutar una vez por cuenta y región:
   ```bash
   npx aws-cdk@2 bootstrap aws://<account-id>/<region>
   ```

### 4.2 Conectar GitHub con AWS (sin claves de acceso)

El despliegue automático usa **OIDC**: GitHub pide un token temporal a AWS en cada corrida, así
que **no hay que guardar claves de AWS en el repositorio**.

1. Crear un **rol IAM por entorno** que confíe en el proveedor OIDC de GitHub, limitado a este
   repositorio, con permiso de `sts:AssumeRole` sobre los roles `cdk-*` que creó el bootstrap.
2. Cargar en GitHub → *Settings* → *Secrets and variables* → *Actions* → **Variables**:
   - `AWS_STAGE_DEPLOY_ROLE_ARN`
   - `AWS_PROD_DEPLOY_ROLE_ARN`
   - `AWS_REGION`
3. Crear los **Environments** `stage` (sin restricción) y `prod` (con *required reviewers*: ahí
   es donde alguien aprueba a mano cada despliegue a producción).
4. Quitar los `if: ${{ false && ... }}` de [.github/workflows/deploy.yml](.github/workflows/deploy.yml)
   — el flujo está escrito y probado, solo está desactivado.

### 4.3 Cargar los secretos (después del primer deploy)

El CDK crea los secretos **vacíos**, nunca con su valor: un secreto en el código o en la
plantilla de CloudFormation queda en el historial de git y en los eventos de CloudFormation.
Tras el primer despliegue, alguien con acceso los carga a mano:

```bash
# Secreto de identidad — lo consume la Lambda `api`
#   VMC_IDENTITY_SECRET lo acuerdan VMC y Subastín (con él VMC firma el JWT del usuario)
#   SESSION_SIGNING_KEY se autogenera; NO reemplazarlo salvo que se quiera invalidar sesiones
aws secretsmanager put-secret-value --secret-id subastin-stage-identity \
  --secret-string '{"VMC_IDENTITY_SECRET":"<acordado con VMC>","SESSION_SIGNING_KEY":"<el generado>"}'

# Secreto de IA — lo consume la Lambda `worker-ai`
aws secretsmanager put-secret-value --secret-id subastin-stage-ai \
  --secret-string '{"GEMINI_API_KEY":"...","PINECONE_API_KEY":"..."}'
```

Los dos secretos de identidad son **distintos a propósito**: si fueran el mismo, un token de
sesión de Subastín podría presentarse como identidad de VMC.

### 4.4 Lo que queda por conectar fuera de AWS

| Qué | Estado |
|---|---|
| **JWT de identidad de VMC** | VMC tiene que firmar el token con el secreto compartido. Contrato y ejemplos en [widget/README.md](widget/README.md) |
| **URL de login de VMC** | Hoy es un valor de ejemplo (`VMC_LOGIN_URL`); VMC debe confirmar la real |
| **Índice de Pinecone** | Se crea con `python -m scripts.helpcenter_upload` (no desde la consola web: el índice tiene que nacer con el modelo de embeddings correcto) |
| **Login del asesor** | La app Next.js todavía no está conectada a Cognito (usa un token pegado a mano en dev). El User Pool ya existe en el stack |
| **Dominio propio de la API** | No bloquea: por ahora se usa la URL que da API Gateway (TD-007) |
| **Slack y HERALD** | Bloqueados por decisiones de negocio abiertas (D-016 y D-011) |

---

## 5. Cómo se despliega

### Automático (lo normal)

| Rama | Qué pasa |
|---|---|
| Cualquier PR | Corre el CI: lint, pruebas, `cdk synth`, build del frontend. **No** despliega |
| Merge a `develop` | Despliega a **stage** solo |
| Merge a `main` | Muestra el `cdk diff`, **espera aprobación** y despliega a **prod** |

### A mano (desde la máquina de alguien, con Docker corriendo)

```bash
cd infra

npx -y aws-cdk@2 synth  -c stage=stage    # solo genera la plantilla, no toca AWS
npx -y aws-cdk@2 diff   -c stage=stage    # qué cambiaría
npx -y aws-cdk@2 deploy -c stage=stage    # despliega

npx -y aws-cdk@2 watch  -c stage=stage    # durante el desarrollo: sube solo el código (~3 s)
```

`prod` es igual cambiando `-c stage=prod`, y **siempre** revisando primero el `diff`.

### Después de desplegar

1. Cargar los secretos (§4.3) y **volver a desplegar no hace falta**: las Lambdas los leen en
   cada arranque en frío.
2. Comprobar que responde: `curl https://<url-del-api>/health`.
3. Invitar a los asesores desde el User Pool de Cognito (no hay auto-registro; el primer login
   los da de alta solos en la tabla `advisors`).
4. Subir el contenido del Centro de Ayuda a Pinecone: `python -m scripts.helpcenter_upload`.
5. Apuntar el frontend a la API: variable `NEXT_PUBLIC_API_URL` con la URL que imprime el deploy.

### Volver atrás

CloudFormation revierte solo si el despliegue falla a la mitad. Para deshacer un despliegue que
sí terminó, se vuelve a desplegar el commit anterior. **En prod los datos están protegidos**
(`RETAIN`): destruir el stack no borra tablas ni bucket.

---

## 6. Detalles que conviene no descubrir por las malas

- **`cdk synth` y `cdk deploy` necesitan Docker** (empaquetan las dependencias de Python dentro
  de una imagen igual a la de Lambda).
- **El esquema de las tablas está escrito dos veces a propósito**: en `infra/stacks/subastin_stack.py`
  (AWS) y en `scripts/local_setup.py` (local). Cambiar una clave o un índice obliga a tocar los
  dos; si no, las pruebas pasan contra un esquema que en AWS no existe.
- **Los índices secundarios (GSI) se deciden antes de crear las tablas.** Agregar uno después
  sobre una tabla con datos es una migración manual, no un `deploy`.
- **La versión de CDK está fijada** en `infra/requirements.txt` y en el workflow de despliegue.
  La librería alpha va siempre en lockstep con `aws-cdk-lib`: subir una sin la otra rompe el
  import.
- **`worker-notify` todavía es un stub**: la cola y la Lambda existen, pero no mandan nada hasta
  que se cierre la decisión del canal de Slack (D-016).
- **Falta configurar alarmas** de CloudWatch (mensajes en la DLQ, errores de los workers, 5xx de
  la API). Está anotado en el stack como pendiente.
- **El login del asesor todavía no usa Cognito.** El User Pool existe y el API Gateway ya valida
  su JWT, pero la app Next.js guarda un token pegado a mano. Conectar la Hosted UI es trabajo
  pendiente, no un paso de despliegue.

---

## 7. Estado verificado (7 de septiembre de 2026)

`cdk synth` corre limpio para **stage** y **prod**, y la plantilla generada se revisó recurso por
recurso:

| Verificado | Resultado |
|---|---|
| Recursos generados | 6 tablas, 4 colas (2 + sus DLQ), 3 Lambdas con sus 3 grupos de logs, 1 HTTP API con 3 rutas, 1 User Pool, 1 bucket, 2 secretos — idéntico en los dos entornos |
| Regla "visibility ≥ 6× timeout" | Se cumple: 720 s contra 120 s, y 180 s contra 30 s |
| Protección de datos en prod | Tablas, bucket **y secretos** con `Retain`; en stage se borran con el stack |
| Aislamiento de prod | CORS solo `vmcsubastas.com`, logs en `INFO` sin contenido de mensajes, rutas `/dev/*` apagadas |
| Índices secundarios | Los 8 GSI coinciden exactamente con los que crea `scripts/local_setup.py` en local |
| Secretos | Nacen vacíos y con la forma JSON que espera el backend; ningún valor viaja en la plantilla |
| Empaquetado de las Lambdas | Las tres se bundlean sin error. Que cada handler *importe* desde el asset lo comprueba `infra/tests/artifact_smoke.py`, y **solo corre en Linux** (en CI): el asset trae binarios compilados para Lambda, así que en Windows no se puede ejecutar |

Pruebas de infraestructura: 13, todas en verde (`python -m pytest infra/tests -q`).

**Lo que esto no demuestra:** nunca se ha desplegado. `synth` valida que la plantilla es
correcta y coherente, no que AWS la acepte — eso solo lo dice el primer `cdk deploy` real, y ahí
suelen aparecer cuotas de la cuenta, permisos del rol y nombres ya tomados.
