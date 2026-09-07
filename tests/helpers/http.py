"""Escenario a nivel de API (TestClient): sesion del widget, mensajes, asesor y handoff.

`client` es la fixture de `tests/conftest.py` (`client` para el chat publico, `advisor_client`
para `/advisor` con el authorizer de dev). `limpiar` registra lo creado para borrarlo.
"""

import uuid

from backend.core import auth
from backend.core.clock import epoch_seconds
from backend.core.config import get_settings

DEV_SECRET = "test-advisor-dev-secret"
FORMULARIO = {"subject": "Problema con mi puja", "detail": "No me deja ofertar en la subasta."}


# ───────────────────────────── Identidad y sesion del widget ─────────────────────────────


def jwt_vmc(user_id: str, **claims) -> str:
    """El JWT de identidad que VMC deja en la pagina (D-001), firmado con el secreto de prueba."""
    payload = {"sub": user_id, "exp": epoch_seconds() + 600, **claims}
    return auth.sign_jwt(payload, get_settings().vmc_identity_secret)


def abrir_sesion(
    client,
    limpiar,
    user_jwt: str | None = None,
    *,
    autenticado: bool = False,
    name: str = "Jorge",
    email: str | None = "jorge@example.test",
    cuu: str | None = "ZEEJ7K",
) -> dict:
    """POST /chat/sessions. Anonima por defecto; `autenticado=True` fabrica un JWT de VMC con
    un usuario nuevo (o se pasa `user_jwt` propio). Registra la conversacion en `limpiar`."""
    if user_jwt is None and autenticado:
        claims = {"name": name}
        if email:
            claims["email"] = email
        if cuu:
            claims["cuu"] = cuu
        user_jwt = jwt_vmc("vmc_" + uuid.uuid4().hex[:8], **claims)
    body = {"user_jwt": user_jwt} if user_jwt else {}
    response = client.post("/chat/sessions", json=body)
    assert response.status_code == 201, response.text
    data = response.json()
    limpiar(data["conversation"]["conversation_id"])
    return data


def auth_headers(sesion: dict) -> dict:
    return {"Authorization": f"Bearer {sesion['token']}"}


def post_mensaje(
    client,
    sesion: dict,
    texto: str = "hola",
    *,
    client_message_id: str | None = None,
    interaction: dict | None = None,
    conversation_id: str | None = None,
):
    """POST .../messages tal cual: devuelve la Response (para probar 409, 422, 429...)."""
    conversation_id = conversation_id or sesion["conversation"]["conversation_id"]
    body = {"client_message_id": client_message_id or "cli-" + uuid.uuid4().hex, "content": texto}
    if interaction is not None:
        body["interaction"] = interaction
    return client.post(
        f"/chat/conversations/{conversation_id}/messages", json=body, headers=auth_headers(sesion)
    )


def enviar(client, sesion: dict, texto: str = "hola", **kwargs) -> dict:
    """Como `post_mensaje`, pero exige el 202 y devuelve el JSON (camino feliz)."""
    response = post_mensaje(client, sesion, texto, **kwargs)
    assert response.status_code == 202, response.text
    return response.json()


def get_mensajes(client, sesion: dict, conversation_id: str | None = None, **params) -> dict:
    """GET .../messages (el sondeo del widget)."""
    conversation_id = conversation_id or sesion["conversation"]["conversation_id"]
    response = client.get(
        f"/chat/conversations/{conversation_id}/messages",
        params=params,
        headers=auth_headers(sesion),
    )
    assert response.status_code == 200, response.text
    return response.json()


def pedir_handoff(client, sesion: dict, limpiar=None, *, formulario: dict = FORMULARIO, **campos):
    """POST .../handoff con el formulario de asesor (D-029). Devuelve la Response; si abrio un
    caso y hay `limpiar`, lo registra."""
    response = client.post(
        f"/chat/conversations/{sesion['conversation']['conversation_id']}/handoff",
        json={**formulario, **campos},
        headers=auth_headers(sesion),
    )
    if response.status_code == 201 and limpiar is not None:
        limpiar(response.json()["conversation"]["conversation_id"])
    return response


# ───────────────────── Asesor (/advisor con el authorizer de dev) ─────────────────────


def token_asesor(sub: str, *, name: str | None = None, email: str | None = None, **extra) -> str:
    """El JWT que en AWS firmaria Cognito; aqui lo firma el secreto de `ADVISOR_DEV_JWT_SECRET`."""
    payload = {"sub": sub, "token_use": "id", "exp": epoch_seconds() + 600, **extra}
    if name:
        payload["name"] = name
    if email:
        payload["email"] = email
    return auth.sign_jwt(payload, DEV_SECRET)


def bearer(sub: str, **claims) -> dict:
    return {"Authorization": f"Bearer {token_asesor(sub, **claims)}"}


def asesor_nuevo(
    client, limpiar, *, name: str = "Ana Prueba", email: str | None = None
) -> tuple[str, dict]:
    """Un asesor efimero (sub aleatorio, auto-alta al primer /me) para no contaminar los GSI
    de otras pruebas. Devuelve `(advisor_id, headers)`."""
    sub = "sub-test-" + uuid.uuid4().hex[:8]
    headers = bearer(sub, name=name, email=email or f"{sub}@vmc.test")
    me = client.get("/advisor/me", headers=headers)
    assert me.status_code == 200, me.text
    limpiar.asesor(me.json()["advisor_id"])
    return me.json()["advisor_id"], headers


def tomar(client, headers: dict, conversation_id: str) -> dict:
    response = client.post(f"/advisor/conversations/{conversation_id}/take", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def cerrar(client, headers: dict, conversation_id: str, **body) -> dict:
    response = client.post(
        f"/advisor/conversations/{conversation_id}/close", headers=headers, json=body or None
    )
    assert response.status_code == 200, response.text
    return response.json()


def tomar_y_cerrar(client, headers: dict, conversation_id: str) -> dict:
    tomar(client, headers, conversation_id)
    return cerrar(client, headers, conversation_id)


def ticket_de(client, headers: dict, conversation_id: str) -> dict:
    response = client.get(f"/advisor/conversations/{conversation_id}/ticket", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()
