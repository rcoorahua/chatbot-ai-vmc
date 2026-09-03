"""DETAILS.md §4.4 / Paso 5 — un ticket por conversación y un asesor por Cognito `sub` bajo
cualquier carrera, no solo en el camino feliz secuencial.

Antes de esto, `ticket_id`/`advisor_id` eran aleatorios y la unicidad dependía de consultar un
GSI (eventualmente consistente) antes de crear: dos requests casi simultáneos podían pasar los
dos el "no existe" y dejar dos filas para la misma conversación o el mismo `cognito_sub`. Con el
id determinista (`ticket_id_for_conversation` / `advisor_id_for_cognito_sub`), el
`attribute_not_exists(pk)` de la creación condicional es la exclusión mutua real: da igual
cuántos threads compitan, solo una escritura gana.

Corre contra dynamodb-local real (no mocks), igual que el resto de `tests/test_dynamo_queries.py`
— la aserción que importa es "una sola fila física", no que el servicio devuelva una.
"""

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, wait

import pytest
from boto3.dynamodb.conditions import Key

from backend.advisors import service as advisors_service
from backend.conversations.models import Conversation, UserType
from backend.core.auth import CognitoClaims
from backend.core.clock import utc_now_iso
from backend.tickets import service as tickets_service

pytestmark = pytest.mark.usefixtures("entorno_dynamo")

N_THREADS = 12


def _conversation(conversation_id: str) -> Conversation:
    now = utc_now_iso()
    return Conversation(
        conversation_id=conversation_id,
        user_type=UserType.AUTHENTICATED,
        user_id="user-uniqueness-test",
        title="No me llega el pago de una subasta",
        last_message_at=now,
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def limpiar_ticket(tablas):
    ids: list[str] = []
    yield ids
    for ticket_id in ids:
        tablas["tickets"].delete_item(Key={"ticket_id": ticket_id})


@pytest.fixture
def limpiar_advisor(tablas):
    ids: list[str] = []
    yield ids
    for advisor_id in ids:
        tablas["advisors"].delete_item(Key={"advisor_id": advisor_id})


def test_open_ticket_concurrente_deja_una_sola_fila(tablas, limpiar_ticket):
    conversation_id = f"conv_test_uniq_{uuid.uuid4().hex[:8]}"
    conversation = _conversation(conversation_id)
    ticket_id = tickets_service.ticket_id_for_conversation(conversation_id)
    limpiar_ticket.append(ticket_id)

    barrera = threading.Barrier(N_THREADS)

    def abrir():
        barrera.wait(timeout=10)  # todos los threads golpean open_ticket lo mas juntos posible
        return tickets_service.open_ticket(conversation)

    with ThreadPoolExecutor(max_workers=N_THREADS) as pool:
        futuros = [pool.submit(abrir) for _ in range(N_THREADS)]
        done, not_done = wait(futuros, timeout=30)
        assert not not_done, "algun thread no termino"
        resultados = [f.result() for f in done]

    assert all(t.ticket_id == ticket_id for t in resultados)

    filas = tablas["tickets"].query(
        IndexName="gsi1_conversation",
        KeyConditionExpression=Key("conversation_id").eq(conversation_id),
    )["Items"]
    assert len(filas) == 1
    assert filas[0]["ticket_id"] == ticket_id


def test_open_ticket_secuencial_inmediato_es_idempotente(tablas, limpiar_ticket):
    conversation_id = f"conv_test_uniq_{uuid.uuid4().hex[:8]}"
    conversation = _conversation(conversation_id)
    ticket_id = tickets_service.ticket_id_for_conversation(conversation_id)
    limpiar_ticket.append(ticket_id)

    primero = tickets_service.open_ticket(conversation)
    segundo = tickets_service.open_ticket(conversation)
    assert primero.ticket_id == segundo.ticket_id == ticket_id

    filas = tablas["tickets"].query(
        IndexName="gsi1_conversation",
        KeyConditionExpression=Key("conversation_id").eq(conversation_id),
    )["Items"]
    assert len(filas) == 1


def test_resolve_advisor_concurrente_primer_login_deja_una_sola_fila(tablas, limpiar_advisor):
    cognito_sub = f"sub-uniq-{uuid.uuid4().hex[:8]}"
    claims = CognitoClaims(sub=cognito_sub, email="asesor@example.com", name="Asesor de Prueba")
    advisor_id = advisors_service.advisor_id_for_cognito_sub(cognito_sub)
    limpiar_advisor.append(advisor_id)

    barrera = threading.Barrier(N_THREADS)

    def entrar():
        barrera.wait(timeout=10)
        return advisors_service.resolve_advisor(claims)

    with ThreadPoolExecutor(max_workers=N_THREADS) as pool:
        futuros = [pool.submit(entrar) for _ in range(N_THREADS)]
        done, not_done = wait(futuros, timeout=30)
        assert not not_done, "algun thread no termino"
        resultados = [f.result() for f in done]

    assert all(a.advisor_id == advisor_id for a in resultados)

    filas = tablas["advisors"].query(
        IndexName="gsi_cognito",
        KeyConditionExpression=Key("cognito_sub").eq(cognito_sub),
    )["Items"]
    assert len(filas) == 1
    assert filas[0]["advisor_id"] == advisor_id
