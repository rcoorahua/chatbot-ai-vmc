"""Lambda `api` — FastAPI completo detras de la ruta $default del HTTP API (decision T2).

Superficies (PLAN.md §3): `chat` (publica, identidad D-001 dentro de FastAPI), `advisor` y
`dashboard` (protegidas por el JWT authorizer de Cognito EN API GATEWAY — aqui no se valida).
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mangum import Mangum

from backend.api.routers import advisor, chat, dashboard
from backend.core.config import get_settings

app = FastAPI(title="Subastin API")

# El widget corre en el dominio de VMC y llama a la API en otro: sin CORS el navegador bloquea
# todo. La API no usa cookies (el token de sesion viaja en Authorization), asi que no hace falta
# `allow_credentials` y "*" es seguro en dev; en stage/prod CORS_ALLOWED_ORIGINS acota a VMC.
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().allowed_origins,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(chat.router)
app.include_router(advisor.router)
app.include_router(dashboard.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


# lifespan="off" es obligatorio: con lifespan activo la Lambda se cuelga en el startup.
handler = Mangum(app, lifespan="off")
