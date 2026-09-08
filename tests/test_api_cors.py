"""Un rechazo del authorizer de dev tiene que llegar al navegador como 401, no como CORS.

`add_middleware` ANTEPONE, asi que el orden en que se agregan decide quien envuelve a quien.
Hasta el 2026-09-08 CORS se agregaba antes que `dev_auth`, o sea que quedaba por DENTRO: el
401 que emite el authorizer salia sin `Access-Control-Allow-Origin`, el navegador lo reportaba
como error de CORS y `fetch` fallaba con un TypeError. La app del asesor mostraba "No se pudo
conectar con el servidor" cuando el problema real era "falta el token".

Se prueba sobre la app REAL (recargando `backend.api.main` con el authorizer encendido), no
sobre una copia armada aqui: el bug estaba justamente en el orden de main.py.
"""

import importlib

import pytest
from fastapi.testclient import TestClient

from backend.core.config import reset_settings

ORIGIN = "http://localhost:3000"


@pytest.fixture
def app_con_authorizer(monkeypatch):
    """`backend.api.main` recargado con ADVISOR_DEV_AUTH=1 (el `if` de main.py corre al
    importar). Se recarga otra vez al salir para que el resto de la suite vea la app limpia."""
    import backend.api.main as main

    monkeypatch.setenv("ADVISOR_DEV_AUTH", "1")
    monkeypatch.setenv("ADVISOR_DEV_JWT_SECRET", "secreto-de-prueba")
    reset_settings()
    yield importlib.reload(main).app
    monkeypatch.undo()
    reset_settings()
    importlib.reload(main)


def test_el_401_del_authorizer_de_dev_trae_las_cabeceras_cors(app_con_authorizer):
    respuesta = TestClient(app_con_authorizer).get(
        "/advisor/conversations", headers={"Origin": ORIGIN}
    )

    assert respuesta.status_code == 401
    # Sin esta cabecera el navegador descarta la respuesta y el frontend nunca ve el 401.
    assert respuesta.headers.get("access-control-allow-origin") is not None


def test_el_preflight_de_una_ruta_protegida_no_pide_token(app_con_authorizer):
    # El navegador manda OPTIONS sin Authorization; en AWS lo responde el API Gateway.
    respuesta = TestClient(app_con_authorizer).options(
        "/advisor/conversations",
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )

    assert respuesta.status_code == 200
    assert respuesta.headers.get("access-control-allow-origin") is not None
