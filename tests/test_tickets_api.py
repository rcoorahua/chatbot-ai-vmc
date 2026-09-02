"""Ciclo de vida del ticket y su API de asesor — RF-023, RF-024, RF-029, RF-031, RF-032.
Taxonomía: ⚠️ propuesta de Aaron, D-008 sigue abierta.

Criterios:
  AC-T1  derivar con el formulario (D-029) abre UN ticket con el tipo sugerido por las reglas,
         su categoría, su prioridad y los datos mínimos que faltan; el del anónimo lleva el
         contacto (RF-003) y el del autenticado su identidad VMC
  AC-T2  tomar la conversación pasa el ticket a IN_PROGRESS y lo asigna (RF-029)
  AC-T3  el asesor confirma o corrige: cambiar el tipo arrastra categoría y datos mínimos,
         una prioridad explícita manda sobre la regla, y todo queda como ADVISOR (RF-024)
  AC-T4  cerrar el caso cierra el ticket con su resolución; un ticket cerrado no se edita
  AC-T5  la bandeja de tickets filtra por estado y por "los míos"; los cerrados no son trabajo
  AC-T6  red de seguridad: un caso escalado sin ticket lo recibe al abrirlo el asesor; una
         conversación que atiende el bot no tiene ticket (RF-023) y responde 404
  AC-T7  la taxonomía se publica marcada como propuesta, para que la app no copie la lista

El authorizer del asesor se simula con el middleware de dev y el encolado a SQS con un doble,
igual que en tests/test_chat_cases.py.
"""

import uuid

import pytest
from boto3.dynamodb.conditions import Key
from fastapi.testclient import TestClient

from backend.api import dev_auth
from backend.api.main import app
from backend.api.routers import chat as chat_router
from backend.core import auth
from backend.core.clock import epoch_seconds
from backend.core.config import get_settings, reset_settings
from backend.tickets import repository as tickets_repository

pytestmark = pytest.mark.usefixtures("entorno_dynamo")

DEV_SECRET = "test-advisor-dev-secret"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ADVISOR_DEV_AUTH", "1")
    monkeypatch.setenv("ADVISOR_DEV_JWT_SECRET", DEV_SECRET)
    monkeypatch.setenv("MAX_MESSAGES_PER_MINUTE", "0")
    reset_settings()
    monkeypatch.setattr(chat_router.jobs, "enqueue_ai_job", lambda job: None)
    yield TestClient(dev_auth.DevCognitoAuthorizer(app))
    reset_settings()


@pytest.fixture
def limpiar(tablas):
    """Borra conversaciones, mensajes, asesores y los tickets que cuelguen de ellas."""
    conversaciones: list[str] = []
    asesores: list[str] = []

    class Registro:
        conversacion = staticmethod(conversaciones.append)
        asesor = staticmethod(asesores.append)

    yield Registro
    for conversation_id in conversaciones:
        for item in tablas["messages"].query(
            KeyConditionExpression=Key("conversation_id").eq(conversation_id)
        )["Items"]:
            tablas["messages"].delete_item(
                Key={"conversation_id": conversation_id, "message_key": item["message_key"]}
            )
        for item in tablas["tickets"].query(
            IndexName="gsi1_conversation",
            KeyConditionExpression=Key("conversation_id").eq(conversation_id),
        )["Items"]:
            tablas["tickets"].delete_item(Key={"ticket_id": item["ticket_id"]})
        tablas["conversations"].delete_item(Key={"conversation_id": conversation_id})
    for advisor_id in asesores:
        tablas["advisors"].delete_item(Key={"advisor_id": advisor_id})


# ───────────────────────────────────── Helpers ─────────────────────────────────────

FORMULARIO = {
    "subject": "Ya pagué y no se refleja",
    "detail": "Hice el pago ayer con el código de Pacífico y mi cuenta sigue sin saldo.",
}
CONTACTO = {"name": "Ana Torres", "email": "ana@example.test"}


def _sesion(client, limpiar, *, autenticado=True) -> dict:
    body = {}
    if autenticado:
        body["user_jwt"] = auth.sign_jwt(
            {
                "sub": "vmc_" + uuid.uuid4().hex[:8],
                "exp": epoch_seconds() + 600,
                "name": "Jorge",
                "email": "jorge@example.test",
            },
            get_settings().vmc_identity_secret,
        )
    response = client.post("/chat/sessions", json=body)
    assert response.status_code == 201, response.text
    sesion = response.json()
    limpiar.conversacion(sesion["conversation"]["conversation_id"])
    return sesion


def _handoff(client, sesion, limpiar, **campos) -> dict:
    response = client.post(
        f"/chat/conversations/{sesion['conversation']['conversation_id']}/handoff",
        json={**FORMULARIO, **campos},
        headers={"Authorization": f"Bearer {sesion['token']}"},
    )
    assert response.status_code == 201, response.text
    caso = response.json()["conversation"]
    limpiar.conversacion(caso["conversation_id"])
    return caso


def _asesor_nuevo(client, limpiar) -> tuple[str, dict]:
    sub = "sub-test-" + uuid.uuid4().hex[:8]
    payload = {"sub": sub, "token_use": "id", "exp": epoch_seconds() + 600, "name": "Ana P."}
    headers = {"Authorization": f"Bearer {auth.sign_jwt(payload, DEV_SECRET)}"}
    me = client.get("/advisor/me", headers=headers)
    assert me.status_code == 200, me.text
    limpiar.asesor(me.json()["advisor_id"])
    return me.json()["advisor_id"], headers


def _ticket(client, headers, conversation_id) -> dict:
    response = client.get(f"/advisor/conversations/{conversation_id}/ticket", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _tomar(client, headers, conversation_id) -> dict:
    response = client.post(f"/advisor/conversations/{conversation_id}/take", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


# ───────────────────── AC-T1: derivar abre el ticket ─────────────────────


def test_el_caso_del_autenticado_abre_un_ticket_clasificado(client, limpiar):
    sesion = _sesion(client, limpiar)
    caso = _handoff(client, sesion, limpiar)
    _, headers = _asesor_nuevo(client, limpiar)

    ticket = _ticket(client, headers, caso["conversation_id"])

    assert ticket["status"] == "PENDING"
    assert ticket["conversation_id"] == caso["conversation_id"]
    # Lo sugieren las reglas sobre el asunto y el detalle: "ya pagué y no se refleja".
    assert ticket["problem_type"] == "PAYMENT_ISSUE"
    assert ticket["category"] == "BILLING" and ticket["priority"] == "HIGH"
    assert ticket["classification_source"] == "RULES" and ticket["classification_rule"] == "pago"
    # RF-024: lo que el asesor todavía tiene que preguntar.
    assert ticket["missing_data"] == ["offer_id", "payment_method", "payment_date", "amount"]
    assert ticket["title"] == FORMULARIO["subject"]
    assert ticket["description"] == FORMULARIO["detail"]
    assert ticket["user_email"] == "jorge@example.test" and ticket["user_type"] == "AUTHENTICATED"
    assert ticket["handoff_reason"] == "user_form"


def test_el_ticket_del_anonimo_lleva_el_contacto_del_formulario(client, limpiar):
    sesion = _sesion(client, limpiar, autenticado=False)
    _handoff(client, sesion, limpiar, **CONTACTO, phone="+51 999 888 777")
    _, headers = _asesor_nuevo(client, limpiar)

    ticket = _ticket(client, headers, sesion["conversation"]["conversation_id"])

    assert ticket["user_type"] == "ANONYMOUS"
    assert ticket["contact_name"] == "Ana Torres"
    assert ticket["contact_email"] == "ana@example.test"
    assert ticket["contact_phone"] == "+51 999 888 777"


def test_un_caso_abre_un_solo_ticket(client, limpiar, tablas):
    sesion = _sesion(client, limpiar)
    caso = _handoff(client, sesion, limpiar)
    _, headers = _asesor_nuevo(client, limpiar)

    # Pedirlo varias veces (la red de seguridad corre en cada lectura) no debe duplicar.
    ids = {_ticket(client, headers, caso["conversation_id"])["ticket_id"] for _ in range(3)}
    en_tabla = tablas["tickets"].query(
        IndexName="gsi1_conversation",
        KeyConditionExpression=Key("conversation_id").eq(caso["conversation_id"]),
    )["Items"]

    assert len(ids) == 1 and len(en_tabla) == 1


def test_el_tipo_y_la_prioridad_salen_del_texto_del_usuario(client, limpiar):
    sesion = _sesion(client, limpiar)
    caso = _handoff(
        client,
        sesion,
        limpiar,
        subject="La sala no carga",
        detail="Estoy en un proceso en vivo y no me deja pujar, ya van 3 veces que sale error.",
    )
    _, headers = _asesor_nuevo(client, limpiar)

    ticket = _ticket(client, headers, caso["conversation_id"])

    assert ticket["problem_type"] == "PLATFORM_BUG" and ticket["category"] == "TECHNICAL"
    # Base MEDIUM, pero el proceso está corriendo: sube a HIGH (MAPEO.md §8).
    assert "EN_VIVO" in ticket["tags"] and ticket["priority"] == "HIGH"


# ───────────────────── AC-T2: tomar asigna el ticket ─────────────────────


def test_tomar_la_conversacion_pone_el_ticket_en_curso(client, limpiar):
    sesion = _sesion(client, limpiar)
    caso = _handoff(client, sesion, limpiar)
    advisor_id, headers = _asesor_nuevo(client, limpiar)

    _tomar(client, headers, caso["conversation_id"])

    ticket = _ticket(client, headers, caso["conversation_id"])
    assert ticket["status"] == "IN_PROGRESS"
    assert ticket["assigned_advisor_id"] == advisor_id and ticket["assigned_at"]


# ───────────────────── AC-T3: el asesor confirma o corrige ─────────────────────


def test_cambiar_el_tipo_arrastra_categoria_datos_minimos_y_deja_rastro(client, limpiar):
    sesion = _sesion(client, limpiar)
    caso = _handoff(client, sesion, limpiar)
    _, headers = _asesor_nuevo(client, limpiar)
    ticket = _ticket(client, headers, caso["conversation_id"])

    response = client.patch(
        f"/advisor/tickets/{ticket['ticket_id']}",
        json={"problem_type": "REFUND_REQUEST"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    corregido = response.json()
    assert corregido["problem_type"] == "REFUND_REQUEST"
    assert corregido["category"] == "BILLING"
    assert corregido["missing_data"] == ["amount", "currency", "transaction_date"]
    assert corregido["classification_source"] == "ADVISOR", "lo confirmó una persona"


def test_registrar_datos_reduce_lo_que_falta(client, limpiar):
    sesion = _sesion(client, limpiar)
    caso = _handoff(client, sesion, limpiar)
    _, headers = _asesor_nuevo(client, limpiar)
    ticket = _ticket(client, headers, caso["conversation_id"])

    primero = client.patch(
        f"/advisor/tickets/{ticket['ticket_id']}",
        json={"collected_data": {"offer_id": "OF-123", "amount": "1500"}},
        headers=headers,
    ).json()
    assert primero["missing_data"] == ["payment_method", "payment_date"]

    segundo = client.patch(
        f"/advisor/tickets/{ticket['ticket_id']}",
        json={"collected_data": {"payment_method": "Pacífico"}},
        headers=headers,
    ).json()
    assert segundo["missing_data"] == ["payment_date"]
    assert segundo["collected_data"]["offer_id"] == "OF-123", "lo anterior no se pierde"


def test_la_prioridad_que_pone_el_asesor_manda_sobre_la_regla(client, limpiar):
    sesion = _sesion(client, limpiar)
    caso = _handoff(client, sesion, limpiar)
    _, headers = _asesor_nuevo(client, limpiar)
    ticket = _ticket(client, headers, caso["conversation_id"])

    bajada = client.patch(
        f"/advisor/tickets/{ticket['ticket_id']}",
        json={"priority": "LOW"},
        headers=headers,
    ).json()
    assert bajada["priority"] == "LOW"

    # Sin prioridad explícita, se recalcula desde tipo + etiquetas.
    recalculada = client.patch(
        f"/advisor/tickets/{ticket['ticket_id']}",
        json={"tags": ["RECURRENTE"]},
        headers=headers,
    ).json()
    assert recalculada["priority"] == "HIGH" and recalculada["tags"] == ["RECURRENTE"]


def test_un_tipo_o_una_etiqueta_inventados_son_422(client, limpiar):
    sesion = _sesion(client, limpiar)
    caso = _handoff(client, sesion, limpiar)
    _, headers = _asesor_nuevo(client, limpiar)
    ticket = _ticket(client, headers, caso["conversation_id"])

    for cuerpo in ({"problem_type": "NO_EXISTE"}, {"tags": ["INVENTADA"]}):
        response = client.patch(
            f"/advisor/tickets/{ticket['ticket_id']}", json=cuerpo, headers=headers
        )
        assert response.status_code == 422, cuerpo


def test_un_ticket_inexistente_es_404(client, limpiar):
    _, headers = _asesor_nuevo(client, limpiar)
    response = client.patch(
        "/advisor/tickets/tick_no_existe", json={"priority": "LOW"}, headers=headers
    )
    assert response.status_code == 404


# ───────────────────── AC-T4: cerrar el caso cierra el ticket ─────────────────────


def test_cerrar_el_caso_cierra_el_ticket_con_su_resolucion(client, limpiar):
    sesion = _sesion(client, limpiar)
    caso = _handoff(client, sesion, limpiar)
    advisor_id, headers = _asesor_nuevo(client, limpiar)
    _tomar(client, headers, caso["conversation_id"])

    cerrada = client.post(
        f"/advisor/conversations/{caso['conversation_id']}/close",
        json={"resolution": "Se aplicó el pago a mano y se avisó al usuario."},
        headers=headers,
    )
    assert cerrada.status_code == 200, cerrada.text

    ticket = _ticket(client, headers, caso["conversation_id"])
    assert ticket["status"] == "CLOSED" and ticket["closed_at"]
    assert ticket["closed_by"] == advisor_id
    assert ticket["resolution"] == "Se aplicó el pago a mano y se avisó al usuario."


def test_cerrar_sin_cuerpo_sigue_funcionando(client, limpiar):
    """El cuerpo es opcional: la app del asesor puede cerrar sin escribir resolución."""
    sesion = _sesion(client, limpiar)
    caso = _handoff(client, sesion, limpiar)
    _, headers = _asesor_nuevo(client, limpiar)
    _tomar(client, headers, caso["conversation_id"])

    cerrada = client.post(
        f"/advisor/conversations/{caso['conversation_id']}/close", headers=headers
    )

    assert cerrada.status_code == 200, cerrada.text
    ticket = _ticket(client, headers, caso["conversation_id"])
    assert ticket["status"] == "CLOSED" and ticket["resolution"] is None


def test_un_ticket_cerrado_ya_no_se_edita(client, limpiar):
    sesion = _sesion(client, limpiar)
    caso = _handoff(client, sesion, limpiar)
    _, headers = _asesor_nuevo(client, limpiar)
    _tomar(client, headers, caso["conversation_id"])
    ticket = _ticket(client, headers, caso["conversation_id"])
    client.post(f"/advisor/conversations/{caso['conversation_id']}/close", headers=headers)

    response = client.patch(
        f"/advisor/tickets/{ticket['ticket_id']}",
        json={"problem_type": "OTHER"},
        headers=headers,
    )

    assert response.status_code == 409


def test_cerrar_el_hilo_del_autenticado_no_inventa_ticket(client, limpiar):
    """El hilo con el bot no es trabajo humano (RF-023): tomarlo sí abre ticket, pero una
    conversación que nunca se escaló no debe dejar rastro en Tickets."""
    sesion = _sesion(client, limpiar)
    _, headers = _asesor_nuevo(client, limpiar)
    hilo_id = sesion["conversation"]["conversation_id"]

    sin_ticket = client.get(f"/advisor/conversations/{hilo_id}/ticket", headers=headers)

    assert sin_ticket.status_code == 404


# ───────────────────── AC-T5: bandeja de tickets ─────────────────────


def test_la_bandeja_filtra_por_estado_y_por_mis_tickets(client, limpiar):
    advisor_id, headers = _asesor_nuevo(client, limpiar)
    mio = _handoff(client, _sesion(client, limpiar), limpiar)
    ajeno = _handoff(client, _sesion(client, limpiar), limpiar)
    _tomar(client, headers, mio["conversation_id"])

    pendientes = client.get(
        "/advisor/tickets", params={"status": "PENDING", "limit": 100}, headers=headers
    ).json()["tickets"]
    conversaciones_pendientes = [t["conversation_id"] for t in pendientes]
    assert ajeno["conversation_id"] in conversaciones_pendientes
    assert mio["conversation_id"] not in conversaciones_pendientes, "ya está en curso"

    mios = client.get("/advisor/tickets", params={"mine": "true"}, headers=headers).json()[
        "tickets"
    ]
    assert [t["conversation_id"] for t in mios] == [mio["conversation_id"]]
    assert all(t["assigned_advisor_id"] == advisor_id for t in mios)


def test_los_tickets_cerrados_salen_de_mi_bandeja(client, limpiar):
    _, headers = _asesor_nuevo(client, limpiar)
    caso = _handoff(client, _sesion(client, limpiar), limpiar)
    _tomar(client, headers, caso["conversation_id"])
    client.post(f"/advisor/conversations/{caso['conversation_id']}/close", headers=headers)

    mios = client.get("/advisor/tickets", params={"mine": "true"}, headers=headers).json()[
        "tickets"
    ]
    cerrados = client.get(
        "/advisor/tickets", params={"mine": "true", "status": "CLOSED"}, headers=headers
    ).json()["tickets"]

    assert caso["conversation_id"] not in [t["conversation_id"] for t in mios]
    assert caso["conversation_id"] in [t["conversation_id"] for t in cerrados]


# ───────────────────── AC-T6: red de seguridad ─────────────────────


def test_un_caso_escalado_sin_ticket_lo_recibe_al_abrirlo_el_asesor(client, limpiar, tablas):
    """Si abrir el ticket falla durante el handoff no se le puede devolver un error al usuario
    (su caso ya es durable). El asesor nunca debe encontrarse un caso sin registro."""
    sesion = _sesion(client, limpiar)
    caso = _handoff(client, sesion, limpiar)
    _, headers = _asesor_nuevo(client, limpiar)
    original = _ticket(client, headers, caso["conversation_id"])
    tablas["tickets"].delete_item(Key={"ticket_id": original["ticket_id"]})

    recreado = _ticket(client, headers, caso["conversation_id"])

    assert recreado["ticket_id"] != original["ticket_id"]
    assert recreado["problem_type"] == "PAYMENT_ISSUE", "se reclasifica desde el formulario"
    assert recreado["description"] == FORMULARIO["detail"], "el detalle sale del hilo"
    assert tickets_repository.find_by_conversation(caso["conversation_id"]) is not None


def test_tomar_un_caso_sin_ticket_tambien_lo_crea(client, limpiar, tablas):
    sesion = _sesion(client, limpiar)
    caso = _handoff(client, sesion, limpiar)
    advisor_id, headers = _asesor_nuevo(client, limpiar)
    original = _ticket(client, headers, caso["conversation_id"])
    tablas["tickets"].delete_item(Key={"ticket_id": original["ticket_id"]})

    _tomar(client, headers, caso["conversation_id"])

    ticket = _ticket(client, headers, caso["conversation_id"])
    assert ticket["status"] == "IN_PROGRESS" and ticket["assigned_advisor_id"] == advisor_id


# ───────────────────── AC-T7: la taxonomía publicada ─────────────────────


def test_la_taxonomia_se_publica_marcada_como_propuesta(client, limpiar):
    _, headers = _asesor_nuevo(client, limpiar)

    catalogo = client.get("/advisor/taxonomy", headers=headers)

    assert catalogo.status_code == 200
    cuerpo = catalogo.json()
    assert cuerpo["proposal"] is True and cuerpo["decision"] == "D-008"
    assert len(cuerpo["problem_types"]) == 12
    assert all(t["when"] for t in cuerpo["problem_types"]), "la app necesita el cuándo"


def test_la_taxonomia_exige_token_de_asesor(client):
    assert client.get("/advisor/taxonomy").status_code == 401
