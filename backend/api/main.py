"""Lambda `api` — FastAPI completo detras de la ruta $default del HTTP API (decision T2).

ESQUELETO: no implementar endpoints aqui sin revisar CLAUDE.md (decisiones abiertas).
"""

from fastapi import FastAPI
from mangum import Mangum

from backend.api.routers import advisor, chat, dashboard

app = FastAPI(title="Subastin API")

# Superficies (los endpoints concretos se definen fase por fase — PLAN.md §8):
app.include_router(
    chat.router
)  # publica: widget VMC (identidad VMC → D-001; sesion anonima → D-018)
app.include_router(advisor.router)  # protegida por JWT authorizer de Cognito a nivel API Gateway
app.include_router(dashboard.router)  # protegida por JWT authorizer de Cognito a nivel API Gateway


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


# lifespan="off" es obligatorio: con lifespan activo la Lambda se cuelga en el startup.
handler = Mangum(app, lifespan="off")
