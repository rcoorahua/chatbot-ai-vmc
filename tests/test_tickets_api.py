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


import pytest
from boto3.dynamodb.conditions import Key

from backend.tickets import repository as tickets_repository
from tests.helpers.http import (
    abrir_sesion,
    asesor_nuevo,
    pedir_handoff,
    ticket_de,
    tomar,
)

pytestmark = pytest.mark.usefixtures("entorno_dynamo")



# ───────────────────────────────────── Helpers ─────────────────────────────────────

FORMULARIO = {
    "subject": "Ya pagué y no se refleja",
    "detail": "Hice el pago ayer con el código de Pacífico y mi cuenta sigue sin saldo.",
}


def _handoff(client, sesion, limpiar, **campos) -> dict:
    """Deriva con el formulario de ESTE archivo (su texto decide el problem_type) y devuelve
    el caso ya registrado para limpiar."""
    response = pedir_handoff(client, sesion, limpiar, formulario=FORMULARIO, **campos)
    assert response.status_code == 201, response.text
    return response.json()["conversation"]


# ───────────────────── AC-T1: derivar abre el ticket ─────────────────────


def test_el_caso_del_autenticado_abre_un_ticket_clasificado(client, limpiar):
    sesion = abrir_sesion(client, limpiar, autenticado=True)
    caso = _handoff(client, sesion, limpiar)
    _, headers = asesor_nuevo(client, limpiar)

    ticket = ticket_de(client, headers, caso["conversation_id"])

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
    # D-010: el CUU viaja del JWT a la conversacion, y de ahi al ticket.
    assert ticket["user_cuu"] == "ZEEJ7K"
    assert ticket["handoff_reason"] == "user_form"


def test_un_caso_abre_un_solo_ticket(client, limpiar, tablas):
    sesion = abrir_sesion(client, limpiar, autenticado=True)
    caso = _handoff(client, sesion, limpiar)
    _, headers = asesor_nuevo(client, limpiar)

    # Pedirlo varias veces (la red de seguridad corre en cada lectura) no debe duplicar.
    ids = {ticket_de(client, headers, caso["conversation_id"])["ticket_id"] for _ in range(3)}
    en_tabla = tablas["tickets"].query(
        IndexName="gsi1_conversation",
        KeyConditionExpression=Key("conversation_id").eq(caso["conversation_id"]),
    )["Items"]

    assert len(ids) == 1 and len(en_tabla) == 1


def test_el_tipo_y_la_prioridad_salen_del_texto_del_usuario(client, limpiar):
    sesion = abrir_sesion(client, limpiar, autenticado=True)
    caso = _handoff(
        client,
        sesion,
        limpiar,
        subject="La sala no carga",
        detail="Estoy en un proceso en vivo y no me deja pujar, ya van 3 veces que sale error.",
    )
    _, headers = asesor_nuevo(client, limpiar)

    ticket = ticket_de(client, headers, caso["conversation_id"])

    assert ticket["problem_type"] == "PLATFORM_BUG" and ticket["category"] == "TECHNICAL"
    # Base MEDIUM, pero el proceso está corriendo: sube a HIGH (MAPEO.md §8).
    assert "EN_VIVO" in ticket["tags"] and ticket["priority"] == "HIGH"


# ───────────────────── AC-T2: tomar asigna el ticket ─────────────────────


def test_tomar_la_conversacion_pone_el_ticket_en_curso(client, limpiar):
    sesion = abrir_sesion(client, limpiar, autenticado=True)
    caso = _handoff(client, sesion, limpiar)
    advisor_id, headers = asesor_nuevo(client, limpiar)

    tomar(client, headers, caso["conversation_id"])

    ticket = ticket_de(client, headers, caso["conversation_id"])
    assert ticket["status"] == "IN_PROGRESS"
    assert ticket["assigned_advisor_id"] == advisor_id and ticket["assigned_at"]


def test_volver_a_tomar_el_hilo_reabre_su_ticket(client, limpiar):
    """Auditoría 2026-09-06: tomar → cerrar → volver a tomar (D-022/D-023) dejaba un ticket
    CLOSED colgando de una conversación IN_ATTENTION, porque el id es determinista por
    conversación y `assign` devolvía el cerrado tal cual. Ahora lo reabre."""
    sesion = abrir_sesion(client, limpiar, autenticado=True)
    hilo_id = sesion["conversation"]["conversation_id"]
    advisor_id, headers = asesor_nuevo(client, limpiar)
    tomar(client, headers, hilo_id)
    cierre = client.post(
        f"/advisor/conversations/{hilo_id}/close", headers=headers, json={"resolution": "Listo"}
    )
    assert cierre.status_code == 200, cierre.text
    assert ticket_de(client, headers, hilo_id)["status"] == "CLOSED"

    tomar(client, headers, hilo_id)

    ticket = ticket_de(client, headers, hilo_id)
    assert ticket["status"] == "IN_PROGRESS" and ticket["assigned_advisor_id"] == advisor_id
    assert ticket["closed_at"] is None and ticket["resolution"] is None


# ───────────────────── AC-T3: el asesor confirma o corrige ─────────────────────


def test_cambiar_el_tipo_arrastra_categoria_datos_minimos_y_deja_rastro(client, limpiar):
    sesion = abrir_sesion(client, limpiar, autenticado=True)
    caso = _handoff(client, sesion, limpiar)
    _, headers = asesor_nuevo(client, limpiar)
    ticket = ticket_de(client, headers, caso["conversation_id"])

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
    sesion = abrir_sesion(client, limpiar, autenticado=True)
    caso = _handoff(client, sesion, limpiar)
    _, headers = asesor_nuevo(client, limpiar)
    ticket = ticket_de(client, headers, caso["conversation_id"])

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
    sesion = abrir_sesion(client, limpiar, autenticado=True)
    caso = _handoff(client, sesion, limpiar)
    _, headers = asesor_nuevo(client, limpiar)
    ticket = ticket_de(client, headers, caso["conversation_id"])

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
    sesion = abrir_sesion(client, limpiar, autenticado=True)
    caso = _handoff(client, sesion, limpiar)
    _, headers = asesor_nuevo(client, limpiar)
    ticket = ticket_de(client, headers, caso["conversation_id"])

    for cuerpo in ({"problem_type": "NO_EXISTE"}, {"tags": ["INVENTADA"]}):
        response = client.patch(
            f"/advisor/tickets/{ticket['ticket_id']}", json=cuerpo, headers=headers
        )
        assert response.status_code == 422, cuerpo


def test_un_ticket_inexistente_es_404(client, limpiar):
    _, headers = asesor_nuevo(client, limpiar)
    response = client.patch(
        "/advisor/tickets/tick_no_existe", json={"priority": "LOW"}, headers=headers
    )
    assert response.status_code == 404


# ───────────────────── AC-T4: cerrar el caso cierra el ticket ─────────────────────


def test_cerrar_el_caso_cierra_el_ticket_con_su_resolucion(client, limpiar):
    sesion = abrir_sesion(client, limpiar, autenticado=True)
    caso = _handoff(client, sesion, limpiar)
    advisor_id, headers = asesor_nuevo(client, limpiar)
    tomar(client, headers, caso["conversation_id"])

    cerrada = client.post(
        f"/advisor/conversations/{caso['conversation_id']}/close",
        json={"resolution": "Se aplicó el pago a mano y se avisó al usuario."},
        headers=headers,
    )
    assert cerrada.status_code == 200, cerrada.text

    ticket = ticket_de(client, headers, caso["conversation_id"])
    assert ticket["status"] == "CLOSED" and ticket["closed_at"]
    assert ticket["closed_by"] == advisor_id
    assert ticket["resolution"] == "Se aplicó el pago a mano y se avisó al usuario."


def test_cerrar_sin_cuerpo_sigue_funcionando(client, limpiar):
    """El cuerpo es opcional: la app del asesor puede cerrar sin escribir resolución."""
    sesion = abrir_sesion(client, limpiar, autenticado=True)
    caso = _handoff(client, sesion, limpiar)
    _, headers = asesor_nuevo(client, limpiar)
    tomar(client, headers, caso["conversation_id"])

    cerrada = client.post(
        f"/advisor/conversations/{caso['conversation_id']}/close", headers=headers
    )

    assert cerrada.status_code == 200, cerrada.text
    ticket = ticket_de(client, headers, caso["conversation_id"])
    assert ticket["status"] == "CLOSED" and ticket["resolution"] is None


def test_un_ticket_cerrado_ya_no_se_edita(client, limpiar):
    sesion = abrir_sesion(client, limpiar, autenticado=True)
    caso = _handoff(client, sesion, limpiar)
    _, headers = asesor_nuevo(client, limpiar)
    tomar(client, headers, caso["conversation_id"])
    ticket = ticket_de(client, headers, caso["conversation_id"])
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
    sesion = abrir_sesion(client, limpiar, autenticado=True)
    _, headers = asesor_nuevo(client, limpiar)
    hilo_id = sesion["conversation"]["conversation_id"]

    sin_ticket = client.get(f"/advisor/conversations/{hilo_id}/ticket", headers=headers)

    assert sin_ticket.status_code == 404


# ───────────────────── AC-T5: bandeja de tickets ─────────────────────


def test_la_bandeja_filtra_por_estado_y_por_mis_tickets(client, limpiar):
    advisor_id, headers = asesor_nuevo(client, limpiar)
    mio = _handoff(client, abrir_sesion(client, limpiar, autenticado=True), limpiar)
    ajeno = _handoff(client, abrir_sesion(client, limpiar, autenticado=True), limpiar)
    tomar(client, headers, mio["conversation_id"])

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
    _, headers = asesor_nuevo(client, limpiar)
    caso = _handoff(client, abrir_sesion(client, limpiar, autenticado=True), limpiar)
    tomar(client, headers, caso["conversation_id"])
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
    (su caso ya es durable). El asesor nunca debe encontrarse un caso sin registro.

    El id es determinista (DETAILS.md §4.4 / Paso 5): recrearlo devuelve el MISMO ticket_id,
    no uno nuevo — es lo que hace posible que dos intentos casi simultaneos de red de
    seguridad nunca dupliquen la fila."""
    sesion = abrir_sesion(client, limpiar, autenticado=True)
    caso = _handoff(client, sesion, limpiar)
    _, headers = asesor_nuevo(client, limpiar)
    original = ticket_de(client, headers, caso["conversation_id"])
    tablas["tickets"].delete_item(Key={"ticket_id": original["ticket_id"]})

    recreado = ticket_de(client, headers, caso["conversation_id"])

    assert recreado["ticket_id"] == original["ticket_id"]
    assert recreado["problem_type"] == "PAYMENT_ISSUE", "se reclasifica desde el formulario"
    assert recreado["description"] == FORMULARIO["detail"], "el detalle sale del hilo"
    assert tickets_repository.find_by_conversation(caso["conversation_id"]) is not None


def test_tomar_un_caso_sin_ticket_tambien_lo_crea(client, limpiar, tablas):
    sesion = abrir_sesion(client, limpiar, autenticado=True)
    caso = _handoff(client, sesion, limpiar)
    advisor_id, headers = asesor_nuevo(client, limpiar)
    original = ticket_de(client, headers, caso["conversation_id"])
    tablas["tickets"].delete_item(Key={"ticket_id": original["ticket_id"]})

    tomar(client, headers, caso["conversation_id"])

    ticket = ticket_de(client, headers, caso["conversation_id"])
    assert ticket["status"] == "IN_PROGRESS" and ticket["assigned_advisor_id"] == advisor_id


# ───────────────────── AC-T7: la taxonomía publicada ─────────────────────


def test_la_taxonomia_se_publica_marcada_como_propuesta(client, limpiar):
    _, headers = asesor_nuevo(client, limpiar)

    catalogo = client.get("/advisor/taxonomy", headers=headers)

    assert catalogo.status_code == 200
    cuerpo = catalogo.json()
    assert cuerpo["proposal"] is True and cuerpo["decision"] == "D-008"
    assert len(cuerpo["problem_types"]) == 12
    assert all(t["when"] for t in cuerpo["problem_types"]), "la app necesita el cuándo"


def test_la_taxonomia_exige_token_de_asesor(client):
    assert client.get("/advisor/taxonomy").status_code == 401


@pytest.fixture
def client(advisor_client):
    return advisor_client
