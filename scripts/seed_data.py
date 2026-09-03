"""Datos de prueba para el entorno local. Reflejan escenarios reales del spec.

Uso:
    docker compose up -d
    python -m scripts.local_setup
    python -m scripts.seed_data

Es IDEMPOTENTE (los ids son fijos: volver a correrlo sobrescribe, no duplica).

Que cubre — los cuatro estados de conversacion (RF-009) y los escenarios criticos:
  conv_001  ANONIMA, BOT_ATTENDING      → FAQ resuelta por el bot sin pedir datos (AC-001)
  conv_002  AUTENTICADA, PENDING_ADVISOR → handoff en espera, IA apagada, no leidos (AC-004)
  conv_003  AUTENTICADA, IN_ATTENTION    → asesor atendiendo, mismo usuario que conv_002
  conv_004  AUTENTICADA, CLOSED          → caso cerrado, con imagen adjunta (AC-007)

NOTA: `expires_at` (TTL) se deja sin valor a proposito — la politica de retencion es D-014 y no
debe convertirse en un supuesto. Los datos de prueba no caducan.
"""

from decimal import Decimal

from backend.advisors.service import advisor_id_for_cognito_sub
from backend.tickets.service import ticket_id_for_conversation
from scripts.local_setup import nombres_de_tabla, recurso_dynamo

# Instante de referencia fijo, para que los datos sean reproducibles entre corridas.
DIA = "2026-08-25"
MES_FACTURACION = "2026-08"

# DETAILS.md §4.4 / Paso 5: advisor_id/ticket_id son deterministas en el sistema real (los
# unicos que los crean son resolve_advisor y open_ticket). Si el seed usara un id fijo tipo
# "adv_001" en vez del mismo derivado, el primer login de ese cognito_sub en una prueba no lo
# encontraria (PK distinta) y crearia una fila duplicada — justo el bug que este paso corrige.
ANA_ID = advisor_id_for_cognito_sub("sub-ana-001")
LUIS_ID = advisor_id_for_cognito_sub("sub-luis-002")
# Nombrados por la conversacion que escalaron, no por el viejo "tick_00N" — evita confundir
# TICKET_CONV_003_ID (el ticket de conv_003) con lo que antes se llamaba "tick_002".
TICKET_CONV_002_ID = ticket_id_for_conversation("conv_002")
TICKET_CONV_003_ID = ticket_id_for_conversation("conv_003")
TICKET_CONV_004_ID = ticket_id_for_conversation("conv_004")


def _t(hora: str) -> str:
    """Timestamp ISO-8601 UTC del dia de referencia."""
    return f"{DIA}T{hora}.000Z"


ADVISORS = [
    {
        "advisor_id": ANA_ID,
        "cognito_sub": "sub-ana-001",
        "name": "Ana Torres",
        "email": "ana.torres@vmc.test",
        "role": "ADVISOR",
        "status": "ACTIVE",
        "created_at": _t("08:00:00"),
        "updated_at": _t("08:00:00"),
        "last_login_at": _t("09:15:00"),
    },
    {
        "advisor_id": LUIS_ID,
        "cognito_sub": "sub-luis-002",
        "name": "Luis Ramos",
        "email": "luis.ramos@vmc.test",
        "role": "ADVISOR",
        "status": "INVITED",  # invitado, aun no entra (RF-006)
        "created_at": _t("08:30:00"),
        "updated_at": _t("08:30:00"),
    },
]

CONVERSATIONS = [
    {
        "conversation_id": "conv_001",
        "user_type": "ANONYMOUS",  # sin user_id: el anonimo no entrega datos (RF-002)
        "status": "BOT_ATTENDING",
        "channel": "WEB",
        "bot_enabled": True,
        "message_count": 2,
        "unread_count": 0,
        "wait_message_sent": False,
        "last_message_preview": "Para participar necesitas registrarte y validar tu documento.",
        "last_message_at": _t("10:00:05"),
        "created_at": _t("10:00:00"),
        "updated_at": _t("10:00:05"),
    },
    {
        "conversation_id": "conv_002",
        "user_id": "user_001",
        "user_type": "AUTHENTICATED",
        "user_name": "Carlos Mendoza",
        "user_email": "carlos.mendoza@example.test",
        "user_company": "Transportes Lima SAC",
        "status": "PENDING_ADVISOR",
        "channel": "WEB",
        "bot_enabled": False,  # IA apagada durante el handoff (RF-025)
        "message_count": 4,
        "unread_count": 2,  # mensajes que el asesor aun no abre (RF-035)
        "wait_message_sent": True,  # el mensaje de espera ya salio una vez (RF-027)
        "handoff_requested_at": _t("11:05:00"),
        "handoff_reason": "SOLICITUD_EXPLICITA",
        "last_message_preview": "Sigo esperando, es urgente por favor",
        "last_message_at": _t("11:12:00"),
        "created_at": _t("11:00:00"),
        "updated_at": _t("11:12:00"),
    },
    {
        "conversation_id": "conv_003",
        "user_id": "user_001",  # mismo usuario que conv_002: prueba el GSI por usuario
        "user_type": "AUTHENTICATED",
        "user_name": "Carlos Mendoza",
        "user_email": "carlos.mendoza@example.test",
        "status": "IN_ATTENTION",
        "channel": "WEB",
        "assigned_advisor_id": ANA_ID,
        "bot_enabled": False,
        "message_count": 3,
        "unread_count": 0,
        "wait_message_sent": False,
        "handoff_requested_at": _t("09:30:00"),
        "handoff_reason": "RAG_SIN_EVIDENCIA",
        "last_message_preview": "Claro, reviso tu caso y te confirmo en unos minutos.",
        "last_message_at": _t("09:45:00"),
        "created_at": _t("09:20:00"),
        "updated_at": _t("09:45:00"),
    },
    {
        "conversation_id": "conv_004",
        "user_id": "user_002",
        "user_type": "AUTHENTICATED",
        "user_name": "Rosa Diaz",
        "user_email": "rosa.diaz@example.test",
        "status": "CLOSED",
        "channel": "WEB",
        "assigned_advisor_id": ANA_ID,
        "bot_enabled": False,
        "message_count": 3,
        "unread_count": 0,
        "wait_message_sent": False,
        "handoff_requested_at": _t("08:10:00"),
        "handoff_reason": "PROBLEMA_CON_VEHICULO",
        "last_message_preview": "Gracias por la ayuda!",
        "last_message_at": _t("08:50:00"),
        "closed_at": _t("08:55:00"),
        "created_at": _t("08:05:00"),
        "updated_at": _t("08:55:00"),
    },
]


def _msg(conv: str, hora: str, mid: str, sender: str, texto: str | None, **extra) -> dict:
    """Construye un mensaje. La SK combina timestamp e id: ordena cronologicamente."""
    creado = _t(hora)
    item = {
        "conversation_id": conv,
        "message_key": f"{creado}#{mid}",  # <- SK
        "message_id": mid,
        "sender_type": sender,
        "message_type": extra.pop("message_type", "TEXT"),
        # Estado tecnico (RF-008): los del usuario ya pasaron por el pipeline; los salientes
        # nacen entregados. Ver MessageStatus en backend/conversations/models.py.
        "status": "PROCESSED" if sender == "USER" else "DELIVERED",
        "created_at": creado,
    }
    if texto is not None:
        item["content"] = texto
    item.update(extra)
    return item


MESSAGES = [
    # conv_001 — FAQ anonima resuelta por el bot (AC-001)
    _msg("conv_001", "10:00:00", "msg_0101", "USER", "como participo en una subasta?",
         client_message_id="cli-0101"),
    _msg("conv_001", "10:00:05", "msg_0102", "BOT",
         "Para participar necesitas registrarte y validar tu documento. "
         "Mas detalle: https://ayuda.vmc.test/participar"),

    # conv_002 — handoff en espera (AC-004)
    _msg("conv_002", "11:00:00", "msg_0201", "USER", "quiero hablar con una persona",
         client_message_id="cli-0201"),
    _msg("conv_002", "11:05:00", "msg_0202", "SYSTEM", "HANDOFF_REQUESTED",
         message_type="SYSTEM", metadata={"reason": "SOLICITUD_EXPLICITA"}),
    _msg("conv_002", "11:05:02", "msg_0203", "BOT",
         "Tu solicitud esta en espera, un asesor te atendera en breve."),
    _msg("conv_002", "11:12:00", "msg_0204", "USER", "Sigo esperando, es urgente por favor",
         client_message_id="cli-0204"),

    # conv_003 — asesor atendiendo
    _msg("conv_003", "09:20:00", "msg_0301", "USER", "no me aparece mi vehiculo adjudicado",
         client_message_id="cli-0301"),
    _msg("conv_003", "09:30:00", "msg_0302", "SYSTEM", "ADVISOR_ASSIGNED",
         message_type="SYSTEM", sender_id=ANA_ID),
    _msg("conv_003", "09:45:00", "msg_0303", "ADVISOR",
         "Claro, reviso tu caso y te confirmo en unos minutos.", sender_id=ANA_ID),

    # conv_004 — cerrada, con imagen (AC-007). El binario vive en S3, aqui solo metadata.
    _msg("conv_004", "08:05:00", "msg_0401", "USER", "el vehiculo llego con este rayon",
         client_message_id="cli-0401", message_type="IMAGE",
         attachment={
             "s3_key": "conversations/conv_004/images/rayon.jpg",
             "mime_type": "image/jpeg",
             "size_bytes": 345821,
             "width": 1280,
             "height": 720,
         }),
    _msg("conv_004", "08:50:00", "msg_0402", "USER", "Gracias por la ayuda!",
         client_message_id="cli-0402"),
    _msg("conv_004", "08:55:00", "msg_0403", "SYSTEM", "CONVERSATION_CLOSED",
         message_type="SYSTEM", sender_id=ANA_ID),
]

TICKETS = [
    {
        "ticket_id": TICKET_CONV_002_ID,
        "conversation_id": "conv_002",
        "user_id": "user_001",
        "user_email": "carlos.mendoza@example.test",
        "status": "PENDING",
        "handoff_reason": "SOLICITUD_EXPLICITA",
        "description": "El usuario pide hablar con una persona.",
        "created_at": _t("11:05:00"),
        "updated_at": _t("11:05:00"),
    },
    {
        "ticket_id": TICKET_CONV_003_ID,
        "conversation_id": "conv_003",
        "user_id": "user_001",
        "user_email": "carlos.mendoza@example.test",
        "status": "IN_PROGRESS",
        "assigned_advisor_id": ANA_ID,
        "handoff_reason": "RAG_SIN_EVIDENCIA",
        "description": "Vehiculo adjudicado no aparece en su cuenta.",
        "created_at": _t("09:30:00"),
        "assigned_at": _t("09:35:00"),
        "updated_at": _t("09:45:00"),
    },
    {
        "ticket_id": TICKET_CONV_004_ID,
        "conversation_id": "conv_004",
        "user_id": "user_002",
        "status": "CLOSED",
        "assigned_advisor_id": ANA_ID,
        "handoff_reason": "PROBLEMA_CON_VEHICULO",
        "description": "Vehiculo entregado con dano visible.",
        "created_at": _t("08:10:00"),
        "assigned_at": _t("08:15:00"),
        "updated_at": _t("08:55:00"),
        "closed_at": _t("08:55:00"),
        "closed_by": ANA_ID,
    },
]


def _uso(conv: str, hora: str, eid: str, tipo: str, proveedor: str, modelo: str, **extra) -> dict:
    creado = _t(hora)
    item = {
        "conversation_id": conv,
        "execution_key": f"{creado}#{eid}",  # <- SK
        "execution_id": eid,
        "execution_type": tipo,
        "provider": proveedor,
        "model": modelo,
        "status": "SUCCESS",
        "billing_month": MES_FACTURACION,
        "created_at": creado,
        "rag_used": False,
        "handoff_triggered": False,
    }
    item.update(extra)
    return item


# Costos como Decimal: DynamoDB no acepta float (perderia precision en dinero).
AI_USAGE = [
    _uso("conv_001", "10:00:01", "exec_0101", "CLASSIFICATION", "ANTHROPIC", "claude-haiku-4-5",
         message_id="msg_0101", intent="FAQ", input_tokens=180, output_tokens=12,
         cached_tokens=150, estimated_cost_usd=Decimal("0.000234"), latency_ms=420),
    _uso("conv_001", "10:00:04", "exec_0102", "RESPONSE", "GOOGLE", "gemini-2.5-flash",
         message_id="msg_0101", intent="FAQ", input_tokens=1450, output_tokens=68,
         estimated_cost_usd=Decimal("0.001120"), latency_ms=1830,
         rag_used=True, rag_results_count=3),
    _uso("conv_002", "11:00:02", "exec_0201", "CLASSIFICATION", "ANTHROPIC", "claude-haiku-4-5",
         message_id="msg_0201", intent="ADVISOR", input_tokens=165, output_tokens=10,
         cached_tokens=150, estimated_cost_usd=Decimal("0.000210"), latency_ms=390,
         handoff_triggered=True),
    _uso("conv_003", "09:20:03", "exec_0301", "CLASSIFICATION", "ANTHROPIC", "claude-haiku-4-5",
         message_id="msg_0301", intent="OTHER", input_tokens=190, output_tokens=11,
         estimated_cost_usd=Decimal("0.000245"), latency_ms=410, handoff_triggered=True),
]


def cargar(verbose: bool = True) -> None:
    """Escribe todos los datos de prueba. Sobrescribe si ya existen (mismos ids)."""
    dynamo = recurso_dynamo()
    t = nombres_de_tabla()
    conjuntos = [
        (t["advisors"], ADVISORS),
        (t["conversations"], CONVERSATIONS),
        (t["messages"], MESSAGES),
        (t["tickets"], TICKETS),
        (t["ai_usage"], AI_USAGE),
    ]
    for nombre_tabla, items in conjuntos:
        tabla = dynamo.Table(nombre_tabla)
        with tabla.batch_writer() as lote:
            for item in items:
                lote.put_item(Item=item)
        if verbose:
            print(f"  {len(items):>2} items -> {nombre_tabla}")


def main() -> None:
    print("Cargando datos de prueba...")
    cargar()
    print("Listo. Verificar: python -m pytest tests/test_dynamo_queries.py -v")


if __name__ == "__main__":
    main()
