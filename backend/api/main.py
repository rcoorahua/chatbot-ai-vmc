"""Lambda `api` — FastAPI completo detras de la ruta $default del HTTP API (decision T2).

Superficies (PLAN.md §3): `chat` (publica, identidad D-001 dentro de FastAPI), `advisor` y
`dashboard` (protegidas por el JWT authorizer de Cognito EN API GATEWAY — aqui no se valida).
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mangum import Mangum

from backend.api import dev_auth, errors, request_log
from backend.api.routers import advisor, chat, dashboard, dev
from backend.core.config import get_settings
from backend.core.observability import configure_logging

configure_logging()
app = FastAPI(title="Subastin API")

# Solo en dev local: imita al JWT authorizer de Cognito para /advisor y /dashboard. En AWS el
# authorizer esta en el API Gateway (T1) y este middleware no se instala (dev_auth.py).
# Va ANTES que CORS a proposito: `add_middleware` antepone, asi que agregarlo primero lo deja
# por DENTRO de CORS y sus 401 salen con las cabeceras CORS. Al reves (como estuvo hasta el
# 2026-09-08) el navegador veia el 401 sin `Access-Control-Allow-Origin`, lo reportaba como
# error de CORS y el `fetch` fallaba con un TypeError: la app del asesor mostraba "No se pudo
# conectar con el servidor" en vez de "sesion invalida", que es lo que de verdad pasaba.
if dev_auth.should_install():
    app.add_middleware(dev_auth.DevCognitoAuthorizer)

# El widget corre en el dominio de VMC y llama a la API en otro: sin CORS el navegador bloquea
# todo. La API no usa cookies (el token de sesion viaja en Authorization), asi que no hace falta
# `allow_credentials` y "*" es seguro en dev; en stage/prod CORS_ALLOWED_ORIGINS acota a VMC.
# En AWS el preflight lo responde el propio API Gateway (cors_preflight del stack).
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().allowed_origins,
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# RNF-006: una linea por peticion (metodo, ruta, estado, duracion) y el motivo de cada rechazo.
# Va AL FINAL a proposito: `add_middleware` antepone, asi que el ultimo en agregarse es el mas
# EXTERNO y ve todas las respuestas. Instalado antes quedaba por dentro del authorizer de dev y
# sus 401 no dejaban rastro (se vio al probarlo: `/advisor/*` rechazado y ni una linea).
request_log.install(app)
# Excepciones de dominio → HTTP en un solo lugar (api/errors.py); los routers no las mapean.
errors.install(app)

app.include_router(chat.router)
app.include_router(advisor.router)
app.include_router(dashboard.router)
# Observabilidad de dev/stage (consola de widget/test.html). En prod responde 404: el gate esta
# por request (`DEV_OBSERVABILITY`), asi que apagarlo no exige redesplegar.
app.include_router(dev.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


# lifespan="off" es obligatorio: con lifespan activo la Lambda se cuelga en el startup.
handler = Mangum(app, lifespan="off")
