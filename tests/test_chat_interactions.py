"""Quick replies del API de chat (D-028, MAPEO.md §3) y sus guardrails de abuso.

Criterios:
  AC-I1  una interaccion bien formada se persiste en `metadata.interaction` del mensaje y el
         API la devuelve tal cual (POST y GET) — es lo que pinta el widget
  AC-I2  sin `interaction` la metadata queda `None`, nunca un dict vacio
  AC-I3  el API valida la FORMA del evento (pydantic); la validacion SEMANTICA — que el
         `action_id`/`value` correspondan al paso vigente del flujo — es del worker (T3,
         chat.py: "el API solo lo PERSISTE"), nunca un 4xx aqui
  AC-I4  RF-038: repetir el mismo `client_message_id` con `interaction` no crea un segundo
         mensaje
  AC-I5  D-005: el rate limit por minuto tambien frena los clicks, y el click rechazado no se
         persiste
  AC-I6  D-005: `MAX_MESSAGE_CHARS` se sigue aplicando aunque el mensaje traiga `interaction`
  AC-I7  los flujos no requieren identidad (MAPEO.md §4.2 "Anonimos"): un anonimo tambien manda
         `interaction`
  AC-I8  el cambio de `MessageIn` no rompio `limits.max_message_chars` en la sesion

Reusa los patrones de `tests/test_chat_api.py` (fixtures `client`/`cola_falsa`/`limpiar`,
helpers `_sesion`/`_auth`) y de `tests/test_guardrails.py` (env + `reset_settings` para D-005).
Nunca llama a Gemini/Pinecone: `cola_falsa` sustituye el encolado real, como en `test_chat_api.py`.
"""

import uuid

import pytest

from backend.core.config import get_settings, reset_settings
from tests.helpers.http import (
    abrir_sesion,
    auth_headers,
    enviar,
    jwt_vmc,
)

pytestmark = pytest.mark.usefixtures("entorno_dynamo", "settings_limpios")


def _interaccion_valida(**overrides) -> dict:
    interaccion = {"action_id": "SELECT_OFFER_TYPE", "value": "LIVE", "flow_version": 1}
    interaccion.update(overrides)
    return interaccion


def _url(sesion: dict) -> str:
    return f"/chat/conversations/{sesion['conversation']['conversation_id']}/messages"


# ───────────────────────── AC-I1: se persiste y se ve en el sondeo ─────────────────────────


def test_la_interaccion_valida_se_persiste_en_metadata_y_el_widget_la_lee(client, limpiar):
    sesion = abrir_sesion(client, limpiar, jwt_vmc("vmc_" + uuid.uuid4().hex[:8], name="Ana"))
    interaccion = _interaccion_valida()

    aceptado = enviar(client, sesion, interaction=interaccion)

    assert aceptado["message"]["metadata"] == {"interaction": interaccion}

    # Es lo que consume el widget: GET /messages debe devolver el mismo metadata (MessageOut).
    listado = client.get(_url(sesion), headers=auth_headers(sesion))
    mensajes = listado.json()["messages"]
    assert mensajes[-1]["metadata"] == {"interaction": interaccion}


def test_la_interaccion_sin_source_message_id_no_deja_la_clave_en_null(client, limpiar):
    """`source_message_id` es opcional; si no viaja, el router hace `exclude_none` (chat.py) y
    no debe aparecer como clave con valor null en la metadata guardada."""
    sesion = abrir_sesion(client, limpiar)

    aceptado = enviar(client, sesion, interaction=_interaccion_valida())

    assert "source_message_id" not in aceptado["message"]["metadata"]["interaction"]


def test_la_interaccion_con_source_message_id_tambien_se_persiste(client, limpiar):
    sesion = abrir_sesion(client, limpiar)
    interaccion = _interaccion_valida(source_message_id="msg-" + uuid.uuid4().hex[:8])

    aceptado = enviar(client, sesion, interaction=interaccion)

    assert aceptado["message"]["metadata"]["interaction"] == interaccion


# ───────────────────────────── AC-I2: sin interaction, metadata None ─────────────────────────────


def test_sin_interaction_la_metadata_queda_null_no_un_dict_vacio(client, limpiar):
    sesion = abrir_sesion(client, limpiar)

    aceptado = enviar(client, sesion, texto="como participo?", interaction=None)

    assert aceptado["message"]["metadata"] is None


# ───────────────── AC-I3: validacion de FORMA aqui; la SEMANTICA es del worker ─────────────────


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"action_id": "select_offer_type"}, id="action_id-minusculas"),
        pytest.param({"action_id": "SELECT OFFER TYPE"}, id="action_id-con-espacios"),
        pytest.param({"action_id": "A" * 65}, id="action_id-65-caracteres"),
        pytest.param({"value": "DROP TABLE"}, id="value-fuera-del-patron"),
        pytest.param({"value": ""}, id="value-vacio"),
        pytest.param({"flow_version": 0}, id="flow_version-cero"),
        pytest.param({"flow_version": -1}, id="flow_version-negativa"),
        pytest.param({"flow_version": "uno"}, id="flow_version-no-entero"),
    ],
)
def test_interaction_mal_formada_es_422(client, limpiar, overrides):
    """Forma invalida (pydantic, InteractionIn) — NO confundir con la validacion semantica de
    abajo, que el API deliberadamente no hace."""
    sesion = abrir_sesion(client, limpiar)

    response = client.post(
        _url(sesion),
        json={
            "client_message_id": "cli-" + uuid.uuid4().hex,
            "content": "hola",
            "interaction": _interaccion_valida(**overrides),
        },
        headers=auth_headers(sesion),
    )

    assert response.status_code == 422


def test_una_interaction_bien_formada_pero_que_no_corresponde_a_ningun_flujo_no_es_error_del_api(
    client, limpiar
):
    """T3 / chat.py (InteractionIn.__doc__): el API solo persiste el evento; validar que
    `action_id`/`value` correspondan al paso VIGENTE del flujo es responsabilidad del worker
    (MAPEO.md §3: "un evento que no coincide con el paso actual se trata como texto normal").
    Aqui no hay flujo activo en la conversacion y aun asi el API responde 202."""
    sesion = abrir_sesion(client, limpiar)
    interaccion = _interaccion_valida(
        action_id="ESTO_NO_EXISTE", value="TAMPOCO_EXISTE", flow_version=999
    )

    aceptado = enviar(client, sesion, interaction=interaccion)

    assert aceptado["message"]["metadata"]["interaction"] == interaccion


# ───────────────────────────── AC-I4: idempotencia (RF-038) ─────────────────────────────


def test_repetir_el_client_message_id_con_interaction_no_duplica(client, limpiar):
    sesion = abrir_sesion(client, limpiar)
    client_message_id = "cli-" + uuid.uuid4().hex
    interaccion = _interaccion_valida()

    primero = enviar(
        client, sesion, client_message_id=client_message_id, interaction=interaccion
    )
    segundo = enviar(
        client, sesion, client_message_id=client_message_id, interaction=interaccion
    )

    assert segundo["duplicate"] is True
    assert segundo["message"]["message_id"] == primero["message"]["message_id"]

    listado = client.get(_url(sesion), headers=auth_headers(sesion))
    coincidencias = [
        m for m in listado.json()["messages"] if m["client_message_id"] == client_message_id
    ]
    assert len(coincidencias) == 1, "no se creo un segundo mensaje"


# ───────────────────────────── AC-I5: D-005 tambien frena los clicks ─────────────────────────────


def test_el_rate_limit_tambien_aplica_a_los_clicks(client, limpiar, monkeypatch):
    monkeypatch.setenv("MAX_MESSAGES_PER_MINUTE", "2")
    reset_settings()
    sesion = abrir_sesion(client, limpiar)
    interaccion = _interaccion_valida()

    for i in range(2):
        aceptado = enviar(
            client, sesion, client_message_id=f"cli-click-{i:04d}", interaction=interaccion
        )
        assert aceptado["duplicate"] is False

    frenado = client.post(
        _url(sesion),
        json={
            "client_message_id": "cli-click-9999",
            "content": "Oferta En Vivo",
            "interaction": interaccion,
        },
        headers=auth_headers(sesion),
    )

    assert frenado.status_code == 429
    assert frenado.headers["Retry-After"] == "60"

    listado = client.get(_url(sesion), headers=auth_headers(sesion))
    assert len(listado.json()["messages"]) == 2, "el click rechazado no se persiste"


# ───────────────────────── AC-I6: MAX_MESSAGE_CHARS sigue aplicando ─────────────────────────


def test_el_limite_de_caracteres_aplica_aunque_venga_interaction(client, limpiar, monkeypatch):
    sesion = abrir_sesion(client, limpiar)
    monkeypatch.setenv("MAX_MESSAGE_CHARS", "5")
    reset_settings()

    response = client.post(
        _url(sesion),
        json={
            "client_message_id": "cli-" + uuid.uuid4().hex,
            "content": "esto es mas largo que cinco caracteres",
            "interaction": _interaccion_valida(),
        },
        headers=auth_headers(sesion),
    )

    assert response.status_code == 422


# ───────────────────────── AC-I7: anonimo tambien manda interaction ─────────────────────────


def test_un_anonimo_tambien_puede_mandar_interaction(client, limpiar):
    sesion = abrir_sesion(client, limpiar)  # sin user_jwt = anonimo
    assert sesion["conversation"]["user_type"] == "ANONYMOUS"

    aceptado = enviar(client, sesion, interaction=_interaccion_valida())

    assert aceptado["duplicate"] is False
    assert aceptado["message"]["metadata"]["interaction"]["value"] == "LIVE"


# ───────────────────────── AC-I8: smoke de limits.max_message_chars ─────────────────────────


def test_la_sesion_sigue_informando_max_message_chars(client, limpiar):
    sesion = abrir_sesion(client, limpiar)
    assert sesion["limits"]["max_message_chars"] == get_settings().max_message_chars
