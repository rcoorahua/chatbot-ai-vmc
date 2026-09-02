"""Pruebas de los patrones de acceso a DynamoDB (PLAN.md §4) contra dynamodb-local real.

Cada prueba valida UN patron de consulta del producto: si un GSI estuviera mal definido, la
consulta falla aqui y no en produccion. Los GSIs no se pueden rellenar despues de crear la
tabla, asi que probarlos ahora es lo que evita una migracion manual mas adelante.

Las pruebas de lectura usan el dataset de scripts/seed_data.py; las de escritura crean sus
propios items con ids unicos para no depender del orden de ejecucion.
"""

import uuid
from decimal import Decimal

import pytest
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

pytestmark = pytest.mark.usefixtures("entorno_dynamo")


# ─────────────────────────── Conversations: bandeja e historial ───────────────────────────


def test_obtener_conversacion_por_id(tablas):
    """Patron base: la app abre un chat por su id (GetItem directo, sin indice)."""
    item = tablas["conversations"].get_item(Key={"conversation_id": "conv_002"})["Item"]

    assert item["status"] == "PENDING_ADVISOR"
    assert item["user_name"] == "Carlos Mendoza"
    assert item["bot_enabled"] is False, "durante el handoff la IA queda apagada (RF-025)"
    assert item["unread_count"] == 2, "mensajes sin abrir por el asesor (RF-035)"


def test_conversaciones_de_un_usuario_por_gsi1(tablas):
    """RF-012: el asesor consulta el historial del usuario autenticado."""
    respuesta = tablas["conversations"].query(
        IndexName="gsi1_user",
        KeyConditionExpression=Key("user_id").eq("user_001"),
        ScanIndexForward=False,  # mas recientes primero
    )

    ids = [c["conversation_id"] for c in respuesta["Items"]]
    assert ids == ["conv_002", "conv_003"], "ordenadas por updated_at descendente"


def test_bandeja_de_pendientes_por_gsi2(tablas):
    """RF-032: la bandeja lista los PENDING_ADVISOR ordenados por antiguedad de espera.

    NO se afirma la lista exacta: la PK de este indice es el ESTADO, asi que cualquier
    conversacion que alguien derive probando a mano en el navegador cae en la misma particion.
    Desde D-029 derivar es enviar un formulario, o sea que pasa a cada rato. Lo que importa
    aqui es el indice: que filtre por estado y que ordene por espera.
    """
    respuesta = tablas["conversations"].query(
        IndexName="gsi2_inbox",
        KeyConditionExpression=Key("status").eq("PENDING_ADVISOR"),
        ScanIndexForward=True,  # el que mas lleva esperando, primero
    )

    items = respuesta["Items"]
    assert "conv_002" in [c["conversation_id"] for c in items], "el pendiente del dataset base"
    assert all(c["status"] == "PENDING_ADVISOR" for c in items)
    esperas = [c["last_message_at"] for c in items]
    assert esperas == sorted(esperas), "el que mas espera va primero"


def test_conversaciones_de_un_asesor_por_gsi3(tablas):
    """Vista "mis conversaciones" del CAM.

    Subconjunto y no igualdad: `scripts/advisor_token --sub sub-ana-001` resuelve a ESTE mismo
    asesor, asi que tomar una conversacion probando a mano suma casos a su particion.
    """
    respuesta = tablas["conversations"].query(
        IndexName="gsi3_advisor",
        KeyConditionExpression=Key("assigned_advisor_id").eq("adv_001"),
    )

    ids = {c["conversation_id"] for c in respuesta["Items"]}
    assert {"conv_003", "conv_004"} <= ids
    assert all(c["assigned_advisor_id"] == "adv_001" for c in respuesta["Items"])


# ─────────────────────────────── Messages: orden y contexto ───────────────────────────────


def test_mensajes_en_orden_cronologico(tablas):
    """La SK `created_at#message_id` da el orden cronologico sin indice adicional."""
    respuesta = tablas["messages"].query(
        KeyConditionExpression=Key("conversation_id").eq("conv_002"),
        ScanIndexForward=True,
    )

    ids = [m["message_id"] for m in respuesta["Items"]]
    assert ids == ["msg_0201", "msg_0202", "msg_0203", "msg_0204"]

    marcas = [m["created_at"] for m in respuesta["Items"]]
    assert marcas == sorted(marcas), "el orden lexicografico de la SK es cronologico"


def test_ventana_de_contexto_para_la_ia(tablas):
    """RF-013: la IA recibe solo los ultimos N mensajes, no el historial completo."""
    respuesta = tablas["messages"].query(
        KeyConditionExpression=Key("conversation_id").eq("conv_002"),
        ScanIndexForward=False,  # descendente + Limit = los N mas recientes
        Limit=2,
    )

    recientes = list(reversed(respuesta["Items"]))  # se reinvierte para leer en orden natural
    assert [m["message_id"] for m in recientes] == ["msg_0203", "msg_0204"]


def test_eventos_de_auditoria_viven_como_mensajes_system(tablas):
    """RF-050: los eventos criticos se registran sin necesidad de una sexta tabla."""
    respuesta = tablas["messages"].query(
        KeyConditionExpression=Key("conversation_id").eq("conv_004"),
    )

    eventos = [m["content"] for m in respuesta["Items"] if m["sender_type"] == "SYSTEM"]
    assert "CONVERSATION_CLOSED" in eventos


def test_imagen_guarda_solo_metadata(tablas):
    """RF-042: el binario vive en S3; DynamoDB solo referencia."""
    respuesta = tablas["messages"].query(
        KeyConditionExpression=Key("conversation_id").eq("conv_004")
        & Key("message_key").begins_with("2026-08-25T08:05"),
    )

    imagen = respuesta["Items"][0]
    assert imagen["message_type"] == "IMAGE"
    assert imagen["attachment"]["s3_key"].startswith("conversations/conv_004/images/")
    assert "content" not in imagen or isinstance(imagen["content"], str)


# ──────────────────────────────────── Tickets ────────────────────────────────────


def test_tickets_de_una_conversacion_por_gsi1(tablas):
    """D-017 sigue abierta (¿varios tickets por conversacion?), pero el modelo ya lo soporta."""
    respuesta = tablas["tickets"].query(
        IndexName="gsi1_conversation",
        KeyConditionExpression=Key("conversation_id").eq("conv_003"),
    )

    assert [t["ticket_id"] for t in respuesta["Items"]] == ["tick_002"]


def test_bandeja_de_tickets_por_estado_gsi3(tablas):
    """Mismo criterio que la bandeja de conversaciones: la PK es el estado, y desde D-029 cada
    formulario enviado a mano abre un ticket PENDING que cae en esta particion."""
    respuesta = tablas["tickets"].query(
        IndexName="gsi3_status",
        KeyConditionExpression=Key("status").eq("PENDING"),
    )

    items = respuesta["Items"]
    assert "tick_001" in [t["ticket_id"] for t in items], "el pendiente del dataset base"
    assert all(t["status"] == "PENDING" for t in items)


def test_tickets_de_un_asesor_por_gsi2(tablas):
    respuesta = tablas["tickets"].query(
        IndexName="gsi2_advisor",
        KeyConditionExpression=Key("assigned_advisor_id").eq("adv_001"),
    )

    assert sorted(t["ticket_id"] for t in respuesta["Items"]) == ["tick_002", "tick_003"]


# ──────────────────────────────────── Advisors ────────────────────────────────────


def test_resolver_asesor_desde_el_sub_de_cognito(tablas):
    """Al llegar un JWT lo unico que tenemos es el `sub`: hay que traducirlo a advisor_id."""
    respuesta = tablas["advisors"].query(
        IndexName="gsi_cognito",
        KeyConditionExpression=Key("cognito_sub").eq("sub-ana-001"),
    )

    assert len(respuesta["Items"]) == 1
    assert respuesta["Items"][0]["advisor_id"] == "adv_001"
    assert respuesta["Items"][0]["status"] == "ACTIVE"


# ──────────────────────────────────── AIUsage ────────────────────────────────────


def test_consumo_de_ia_de_una_conversacion(tablas):
    """Trazabilidad de costo por conversacion (PK directa)."""
    respuesta = tablas["ai_usage"].query(
        KeyConditionExpression=Key("conversation_id").eq("conv_001"),
    )

    tipos = sorted(u["execution_type"] for u in respuesta["Items"])
    assert tipos == ["CLASSIFICATION", "RESPONSE"], "Haiku clasifica y Gemini redacta (RF-015/020)"


def test_costo_mensual_agregado_por_gsi_billing(tablas):
    """El GSI por mes evita escanear toda la tabla para calcular el gasto."""
    respuesta = tablas["ai_usage"].query(
        IndexName="gsi_billing",
        KeyConditionExpression=Key("billing_month").eq("2026-08"),
    )

    assert len(respuesta["Items"]) >= 4

    total = sum(u["estimated_cost_usd"] for u in respuesta["Items"])
    assert isinstance(total, Decimal), "el costo se guarda como Decimal, nunca float"
    assert total > 0

    por_proveedor = {}
    for u in respuesta["Items"]:
        por_proveedor[u["provider"]] = por_proveedor.get(u["provider"], 0) + u["input_tokens"]
    assert set(por_proveedor) == {"ANTHROPIC", "GOOGLE"}


# ───────────────────── Patrones criticos de escritura (validan el modelo) ─────────────────────


def test_toma_de_conversacion_es_atomica(tablas, conversacion_temporal):
    """AC-005: si dos asesores toman el mismo caso a la vez, solo uno gana.

    Se resuelve con UpdateItem condicional, sin bloqueos ni transacciones. Los asesores son
    ids efimeros: usar `adv_001` contaminaria el GSI3 que consultan otras pruebas.
    """
    conv_id = conversacion_temporal()
    primero = f"adv_test_{uuid.uuid4().hex[:6]}"
    segundo = f"adv_test_{uuid.uuid4().hex[:6]}"

    tablas["conversations"].put_item(
        Item={
            "conversation_id": conv_id,
            "status": "PENDING_ADVISOR",
            "user_type": "ANONYMOUS",
            "channel": "WEB",
            "bot_enabled": False,
            "message_count": 1,
            "last_message_at": "2026-08-25T12:00:00.000Z",
            "created_at": "2026-08-25T12:00:00.000Z",
            "updated_at": "2026-08-25T12:00:00.000Z",
        }
    )

    def tomar(advisor_id: str):
        return tablas["conversations"].update_item(
            Key={"conversation_id": conv_id},
            UpdateExpression="SET assigned_advisor_id = :a, #s = :atendiendo",
            ConditionExpression="attribute_not_exists(assigned_advisor_id) AND #s = :pendiente",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":a": advisor_id,
                ":atendiendo": "IN_ATTENTION",
                ":pendiente": "PENDING_ADVISOR",
            },
        )

    tomar(primero)  # el primero gana

    with pytest.raises(ClientError) as error:
        tomar(segundo)  # el segundo debe rebotar
    assert error.value.response["Error"]["Code"] == "ConditionalCheckFailedException"

    item = tablas["conversations"].get_item(Key={"conversation_id": conv_id})["Item"]
    assert item["assigned_advisor_id"] == primero
    assert item["status"] == "IN_ATTENTION"


def test_reintento_con_mismo_client_message_id_no_duplica(
    tablas, entorno_dynamo, conversacion_temporal, cliente_bajo_nivel
):
    """RF-038 / RNF-004: un reintento del frontend no puede crear dos mensajes.

    El `created_at` lo pone el servidor, asi que la SK cambiaria en cada reintento. La solucion
    es una transaccion con un item marcador `CMID#<client_message_id>` y condicion de unicidad
    (ajuste 4 de la revision del modelo, PLAN.md §4).
    """
    conv_id = conversacion_temporal()
    client_message_id = f"cli-{uuid.uuid4().hex[:8]}"
    tabla_mensajes = entorno_dynamo["messages"]
    cliente = cliente_bajo_nivel

    def guardar(created_at: str, message_id: str):
        cliente.transact_write_items(
            TransactItems=[
                {
                    "Put": {
                        "TableName": tabla_mensajes,
                        "Item": {
                            "conversation_id": {"S": conv_id},
                            "message_key": {"S": f"CMID#{client_message_id}"},
                        },
                        "ConditionExpression": "attribute_not_exists(message_key)",
                    }
                },
                {
                    "Put": {
                        "TableName": tabla_mensajes,
                        "Item": {
                            "conversation_id": {"S": conv_id},
                            "message_key": {"S": f"{created_at}#{message_id}"},
                            "message_id": {"S": message_id},
                            "sender_type": {"S": "USER"},
                            "message_type": {"S": "TEXT"},
                            "content": {"S": "hola"},
                            "client_message_id": {"S": client_message_id},
                            "created_at": {"S": created_at},
                        },
                    }
                },
            ]
        )

    guardar("2026-08-25T12:00:00.000Z", "msg_x1")

    with pytest.raises(ClientError) as error:
        guardar("2026-08-25T12:00:03.000Z", "msg_x2")  # reintento: otro timestamp, mismo cliente
    assert error.value.response["Error"]["Code"] == "TransactionCanceledException"

    reales = tablas["messages"].query(
        KeyConditionExpression=Key("conversation_id").eq(conv_id),
    )["Items"]
    mensajes = [m for m in reales if not m["message_key"].startswith("CMID#")]
    assert len(mensajes) == 1, "el reintento no debe crear un segundo mensaje"
    assert mensajes[0]["message_id"] == "msg_x1"
