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
| **Lambda** ×3 | Todo el cómputo | `api` (FastAPI completo vía Mangum), `worker-ai` (responde el bot), `worker-notify` (notificaciones, fuera del MVP) |
| **DynamoDB** ×6 tablas | Toda la persistencia | `conversations`, `messages`, `tickets`, `advisors`, `ai-usage`, `rate-limits`. Todas *on-demand* (`PAY_PER_REQUEST`) |
| **SQS** ×2 colas + 2 DLQ | Desacoplar la IA del request HTTP | `ai-jobs` (el bot) y `notifications`. Cada una con su *dead letter queue* tras 3 intentos |
| **Cognito** | Login de los asesores | User Pool sin auto-registro: solo por invitación. El JWT lo valida el API Gateway, no el código |
| **S3** | Imágenes que manda el usuario | Bucket privado (todo acceso público bloqueado); se sirven con URLs firmadas |
| **Secrets Manager** ×2 | Credenciales | Un secreto de identidad (para la API) y uno de IA (para el worker). Ver §4.3 |
| **CloudWatch Logs** | Logs de las 3 Lambdas | Retención: 14 días en stage, 90 en prod |

**Servicios de terceros** (no son de AWS, hacen falta sus credenciales): **Gemini** (clasifica y
redacta), **Pinecone** (búsqueda del Centro de Ayuda) y, más adelante, **HERALD** (catálogo de
vehículos, bloqueado por la decisión D-011).

### Cómo se conecta todo

Todo entra por el API Gateway. La Lambda `api` atiende lo síncrono y escribe en DynamoDB; cuando
hay que llamar a un modelo, encola en SQS y responde al instante, y la Lambda `worker-ai` toma el
trabajo, consulta Pinecone y Gemini, y guarda la respuesta. La segunda cola y su Lambda
(`worker-notify`) quedan desplegadas pero inactivas: las notificaciones no entran en el MVP. El
diagrama está en [README.md](README.md) §3 y el detalle en [docs/PLAN.md](docs/PLAN.md).

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

#### Quién puede actualizar un secreto después

Cualquiera con permiso IAM de `secretsmanager:PutSecretValue` **sobre ese secreto**, desde la
consola de AWS (Secrets Manager → el secreto → *Retrieve secret value* → *Edit*) o con el comando
de arriba. **No hace falta desplegar ni pedírselo a quien administra la infraestructura**: pedir
un permiso acotado a esos dos secretos es suficiente, y es lo razonable — rotar una API key de
Gemini no debería requerir un `cdk deploy`.

Dos cosas que hay que saber al rotar una clave:

- **Los cambios no se aplican al instante.** Cada Lambda lee los secretos **una vez al arrancar**
  y los guarda mientras el proceso viva. Las instancias que ya están calientes siguen con el
  valor viejo hasta que AWS las recicla (minutos, sin garantía). Para forzarlo: desplegar de
  nuevo, o cambiar cualquier variable de entorno de la función — las dos cosas obligan a un
  arranque en frío.
- **Hay que mandar el JSON completo.** `put-secret-value` **reemplaza** todo el valor: si mandas
  solo `GEMINI_API_KEY`, borras `PINECONE_API_KEY`. Desde la consola, editando campo por campo,
  esto no pasa.
- **Cuidado con `SESSION_SIGNING_KEY`**: cambiarla invalida todas las sesiones abiertas del chat
  (los usuarios pierden su conversación en curso). Solo se toca a propósito.

### 4.4 Lo que queda por conectar fuera de AWS

| Qué | Estado |
|---|---|
| **JWT de identidad de VMC** | VMC tiene que firmar el token con el secreto compartido. Contrato y ejemplos en [widget/README.md](widget/README.md) |
| **URL de login de VMC** | Hoy es un valor de ejemplo (`VMC_LOGIN_URL`); VMC debe confirmar la real |
| **Índice de Pinecone** | Se crea con `python -m scripts.helpcenter_upload` (no desde la consola web: el índice tiene que nacer con el modelo de embeddings correcto) |
| **Dominio propio de la API** | No bloquea: por ahora se usa la URL que da API Gateway (TD-007) |
| **HERALD** (catálogo) | Bloqueado por una decisión de negocio abierta (D-011) |

---

## 5. El widget: cómo se publica y quién lo sirve

El widget **no se despliega con el CDK**. Es un archivo JavaScript estático,
`widget/subastin.js` (~250 KB, sin dependencias externas), y la página de VMC lo carga con dos
etiquetas `<script>`:

```html
<script>
  window.subastinSettings = {
    apiUrl: "https://<url-del-api-gateway>",
    userJwt: "<JWT firmado por el servidor de VMC>"   // solo si hay sesión iniciada
  };
</script>
<script src="https://<host>/subastin.js" async></script>
```

El contrato completo (claims del JWT, ejemplos en PHP y Node, y cómo avisar un cambio de sesión
sin recargar la página) está en [widget/README.md](widget/README.md).

### Dónde alojarlo

Tres opciones, de más simple a más operable:

| Opción | Cuándo conviene | Contra |
|---|---|---|
| **Lo sirve VMC** junto a sus propios assets | Es lo más simple: el archivo entra en el despliegue que VMC ya hace | Cada actualización del widget depende de un despliegue de VMC |
| **S3 + CloudFront** en nuestra cuenta | Publicamos sin depender de VMC; CDN, HTTPS y caché resueltos | Un bucket, una distribución y una invalidación de caché más que mantener |
| Un CDN de terceros | — | No aporta nada sobre las anteriores |

**Recomendación: empezar con la primera** (que VMC lo sirva) y pasar a S3 + CloudFront solo
cuando actualizar el widget sin esperar a VMC empiece a estorbar. No hay que decidirlo ahora:
cambiar de una a otra es cambiar una URL en la etiqueta `<script>`.

### Cómo se versiona

`subastin.js` es un archivo **generado**: las fuentes son los 14 fragmentos de `widget/src/*.js`
y se arma con `node widget/build.mjs`. El resultado se versiona en el repo y el CI verifica que
esté al día, así que **lo que hay que publicar es siempre el archivo del repo**, sin pasos
intermedios.

Dos cosas que conviene acordar con VMC antes de publicar:

- **La caché.** Un `subastin.js` cacheado un año deja a los usuarios con la versión vieja. Lo
  habitual es servirlo con caché corta (minutos) o con la versión en el nombre
  (`subastin.v3.js`), y en ese caso VMC cambia la etiqueta en cada actualización.
- **El orden del despliegue.** El widget habla con la API; si una versión nueva del widget usa
  algo que la API todavía no tiene, se rompe. La regla es simple: **primero la API, después el
  widget** — el backend siempre acepta lo que mandaba el widget anterior.

No hace falta hacer nada especial para probarlo: `widget/test.html` simula la página de VMC en
local, con el mismo contrato.

---

## 6. Cómo se despliega

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

## 7. Detalles que conviene no descubrir por las malas

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
- **Las notificaciones no entran en el MVP.** La cola y la Lambda `worker-notify` existen y se
  despliegan, pero hoy no envían nada: el canal y el formato de los avisos están sin definir y
  quedaron fuera de este alcance. No bloquea nada; el sistema funciona completo sin ellas.
- **Falta configurar alarmas** de CloudWatch (mensajes en la DLQ, errores de los workers, 5xx de
  la API). Está anotado en el stack como pendiente. **Cuesta centavos**: una alarma estándar vale
  ~US$0.10 al mes y las primeras 10 entran en la capa gratuita, así que las 5 o 6 que hacen falta
  salen gratis o casi; los avisos por correo vía SNS también son gratuitos en ese volumen.
  Confirmar los precios vigentes de la región antes de prometer la cifra. Lo caro no es la
  alarma: es enterarse tarde de que la cola de errores lleva días llenándose.

---

## 8. Estado verificado (7 de septiembre de 2026)

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
