"""Identidad del chat (D-001) y token de sesion del widget — RF-005 / RNF-005 / AC-008.

Criterios:
  AC-A1  un JWT firmado por VMC con el secreto compartido identifica al usuario
  AC-A2  cualquier alteracion (firma, secreto, algoritmo, expiracion) se rechaza
  AC-A3  el token de sesion de Subastin viaja y vuelve con la misma informacion
  AC-A4  sin token de sesion valido la API responde 401 (nada del frontend se cree sin firma)

Sin DynamoDB: todo es criptografia y parseo, corre en cualquier entorno.
"""

import base64
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core import auth
from backend.core.clock import epoch_seconds
from backend.core.config import get_settings, reset_settings

SECRET = "secreto-de-prueba"


def _jwt_vmc(claims: dict, secret: str | None = None) -> str:
    return auth.sign_jwt(claims, secret or get_settings().vmc_identity_secret)


def _en_una_hora() -> int:
    return epoch_seconds() + 3600


# ───────────────────────────── AC-A1: identidad valida ─────────────────────────────


def test_jwt_valido_de_vmc_identifica_al_usuario():
    token = _jwt_vmc(
        {"sub": "215011", "name": "Aaron", "email": "aaron@example.test", "exp": _en_una_hora()}
    )

    identity = auth.verify_vmc_identity(token)

    assert identity == auth.VmcIdentity(
        user_id="215011", name="Aaron", email="aaron@example.test"
    )


def test_acepta_user_id_como_en_el_jwt_de_intercom():
    # VMC ya firma un JWT asi para Intercom; reutilizar ese codigo con otro secreto es el
    # camino mas corto para ellos.
    token = _jwt_vmc({"user_id": "215011", "exp": _en_una_hora()})

    assert auth.verify_vmc_identity(token).user_id == "215011"


def test_el_nombre_se_acota_antes_de_persistir():
    token = _jwt_vmc({"sub": "1", "name": "x" * 500, "exp": _en_una_hora()})

    assert len(auth.verify_vmc_identity(token).name) == 120


# ───────────────────────────── AC-A2: todo lo alterado se rechaza ─────────────────────────────


def test_firma_con_otro_secreto_se_rechaza():
    token = _jwt_vmc({"sub": "215011", "exp": _en_una_hora()}, secret="otro-secreto")

    with pytest.raises(auth.IdentityError, match="firma"):
        auth.verify_vmc_identity(token)


def test_payload_alterado_se_rechaza():
    token = _jwt_vmc({"sub": "215011", "exp": _en_una_hora()})
    header, _, signature = token.split(".")
    otro_usuario = (
        base64.urlsafe_b64encode(json.dumps({"sub": "1", "exp": _en_una_hora()}).encode())
        .rstrip(b"=")
        .decode()
    )

    with pytest.raises(auth.IdentityError, match="firma"):
        auth.verify_jwt(f"{header}.{otro_usuario}.{signature}", SECRET)


def test_algoritmo_none_se_rechaza():
    # El ataque clasico: declarar `alg: none` para que el verificador salte la firma.
    header = base64.urlsafe_b64encode(b'{"alg":"none","typ":"JWT"}').rstrip(b"=").decode()
    body = (
        base64.urlsafe_b64encode(json.dumps({"sub": "1", "exp": _en_una_hora()}).encode())
        .rstrip(b"=")
        .decode()
    )

    with pytest.raises(auth.IdentityError, match="algoritmo"):
        auth.verify_jwt(f"{header}.{body}.firma-cualquiera", SECRET)


def test_token_expirado_se_rechaza():
    token = auth.sign_jwt({"sub": "1", "exp": epoch_seconds() - 1}, SECRET)

    with pytest.raises(auth.IdentityError, match="expirado"):
        auth.verify_jwt(token, SECRET)


def test_token_sin_exp_se_rechaza():
    # Un token sin caducidad seria una credencial permanente del chat.
    token = auth.sign_jwt({"sub": "1"}, SECRET)

    with pytest.raises(auth.IdentityError, match="exp"):
        auth.verify_jwt(token, SECRET)


@pytest.mark.parametrize("basura", ["", "abc", "a.b", "a.b.c", "no.es.un.jwt"])
def test_token_mal_formado_se_rechaza(basura):
    with pytest.raises(auth.IdentityError):
        auth.verify_jwt(basura, SECRET)


def test_jwt_sin_identidad_se_rechaza():
    token = _jwt_vmc({"name": "Aaron", "exp": _en_una_hora()})

    with pytest.raises(auth.IdentityError, match="sub"):
        auth.verify_vmc_identity(token)


def test_sin_secreto_configurado_es_error_de_despliegue(monkeypatch):
    monkeypatch.setenv("VMC_IDENTITY_SECRET", "")
    reset_settings()
    try:
        with pytest.raises(auth.IdentityConfigurationError):
            auth.verify_vmc_identity("lo.que.sea")
    finally:
        reset_settings()


# ───────────────────────────── AC-A3: token de sesion ─────────────────────────────


def test_el_token_de_sesion_vuelve_con_la_misma_informacion():
    session = auth.new_session(
        user_type=auth.USER_TYPE_AUTHENTICATED,
        conversation_id="conv-1",
        user_id="215011",
        user_name="Aaron",
    )

    decoded = auth.decode_session_token(auth.issue_session_token(session))

    assert decoded == session


def test_la_sesion_anonima_dura_lo_configurado(monkeypatch):
    monkeypatch.setenv("ANONYMOUS_SESSION_TTL_HOURS", "1")
    reset_settings()
    try:
        session = auth.new_session(
            user_type=auth.USER_TYPE_ANONYMOUS, conversation_id="c", user_id=None, user_name=None
        )
        assert 3595 <= session.expires_at - epoch_seconds() <= 3600
    finally:
        reset_settings()


def test_un_token_de_sesion_no_sirve_como_identidad_vmc():
    # Los dos tokens usan claves distintas a proposito: el de sesion lo emite Subastin y no
    # debe poder presentarse como si lo hubiera firmado VMC.
    session = auth.new_session(
        user_type=auth.USER_TYPE_AUTHENTICATED, conversation_id="c", user_id="1", user_name=None
    )

    with pytest.raises(auth.IdentityError):
        auth.verify_vmc_identity(auth.issue_session_token(session))


# ───────────────────────────── AC-A4: dependency de FastAPI ─────────────────────────────


@pytest.fixture
def app_protegida():
    app = FastAPI()

    @app.get("/quien-soy")
    def quien_soy(session: auth.CurrentSession) -> dict:
        return {"cid": session.conversation_id, "typ": session.user_type}

    return TestClient(app)


def test_sin_authorization_responde_401(app_protegida):
    assert app_protegida.get("/quien-soy").status_code == 401


@pytest.mark.parametrize("valor", ["Bearer", "Bearer basura", "Basic abc", "token"])
def test_authorization_invalido_responde_401(app_protegida, valor):
    assert app_protegida.get("/quien-soy", headers={"Authorization": valor}).status_code == 401


def test_con_token_de_sesion_valido_entra(app_protegida):
    session = auth.new_session(
        user_type=auth.USER_TYPE_ANONYMOUS, conversation_id="conv-9", user_id=None, user_name=None
    )
    token = auth.issue_session_token(session)

    response = app_protegida.get("/quien-soy", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json() == {"cid": "conv-9", "typ": "ANONYMOUS"}


# ───────────────────── Claims de Cognito desde el evento del API Gateway (T1) ─────────────────────
#
# En AWS el authorizer valida el JWT y la Lambda recibe los claims en el evento; el backend no
# ve el token. Estas pruebas cubren ese camino sin API Gateway: el evento se arma a mano con la
# forma exacta del payload 2.0 del HTTP API.


def _evento(claims):
    return {"version": "2.0", "requestContext": {"authorizer": {"jwt": {"claims": claims}}}}


def test_los_claims_del_evento_dan_el_asesor():
    claims = auth.cognito_claims_from_event(
        _evento({"sub": "abc-123", "email": "ana@vmc.test", "name": "Ana"})
    )
    assert claims == auth.CognitoClaims(sub="abc-123", email="ana@vmc.test", name="Ana")


def test_sin_name_se_usa_el_username_de_cognito():
    claims = auth.cognito_claims_from_event(_evento({"sub": "s", "cognito:username": "ana"}))
    assert claims.name == "ana"


@pytest.mark.parametrize(
    "evento",
    [
        None,  # request que no paso por Mangum (p. ej. TestClient sin middleware)
        {"version": "2.0", "requestContext": {}},  # ruta sin authorizer
        _evento({}),
        _evento({"sub": "   "}),
        _evento({"sub": "x" * 200}),
    ],
)
def test_un_evento_sin_claims_validos_se_rechaza(evento):
    with pytest.raises(auth.AdvisorAuthError):
        auth.cognito_claims_from_event(evento)
