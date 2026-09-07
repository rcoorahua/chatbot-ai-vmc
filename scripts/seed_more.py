"""Datos EXTRA con fecha de hoy, para ver la bandeja "viva" en local.

Uso:
    python -m scripts.seed_more            # usa la fecha de hoy (UTC)
    python -m scripts.seed_more 2026-09-07 # o una fecha explicita

Idempotente: ids fijos (conv_h0N), volver a correrlo sobrescribe. NO toca el seed base
(conv_001..conv_004) — este solo agrega. Para limpiar todo: python -m scripts.reset_local.

ponytail: espeja la forma de scripts/seed_data.py a mano en vez de importarlo — DIA alli es
constante de modulo y parametrizarlo era mas cambio que copiar tres helpers.
"""

import sys
from datetime import UTC, datetime
from decimal import Decimal

from backend.advisors.service import advisor_id_for_cognito_sub
from backend.tickets.service import ticket_id_for_conversation
from scripts.local_setup import nombres_de_tabla, recurso_dynamo

DIA = sys.argv[1] if len(sys.argv) > 1 else datetime.now(UTC).strftime("%Y-%m-%d")
MES_FACTURACION = DIA[:7]

ANA_ID = advisor_id_for_cognito_sub("sub-ana-001")
LUIS_ID = advisor_id_for_cognito_sub("sub-luis-002")


def _t(hora: str) -> str:
    return f"{DIA}T{hora}.000Z"


CONVERSATIONS = [
    {
        "conversation_id": "conv_h01",
        "user_id": "user_101",
        "user_type": "AUTHENTICATED",
        "user_name": "Diego Salazar",
        "user_email": "diego.salazar@example.test",
        "user_company": "Logística Andina SAC",
        "status": "PENDING_ADVISOR",
        "channel": "WEB",
        "bot_enabled": False,
        "message_count": 3,
        "unread_count": 2,
        "wait_message_sent": True,
        "handoff_requested_at": _t("13:40:00"),
        "handoff_reason": "advisor_request",
        "last_message_preview": "Necesito ayuda con el pago de mi adjudicación",
        "last_message_at": _t("13:42:00"),
        "created_at": _t("13:35:00"),
        "updated_at": _t("13:42:00"),
    },
    {
        "conversation_id": "conv_h02",
        "user_id": "user_102",
        "user_type": "AUTHENTICATED",
        "user_name": "María Fernández",
        "user_email": "maria.fernandez@example.test",
        "status": "PENDING_ADVISOR",
        "channel": "WEB",
        "bot_enabled": False,
        "message_count": 2,
        "unread_count": 1,
        "wait_message_sent": True,
        "handoff_requested_at": _t("14:05:00"),
        "handoff_reason": "faq_no_evidence",
        "last_message_preview": "¿Pueden revisar mi caso de garantía?",
        "last_message_at": _t("14:06:00"),
        "created_at": _t("14:00:00"),
        "updated_at": _t("14:06:00"),
    },
    {
        "conversation_id": "conv_h03",
        "user_id": "user_103",
        "user_type": "AUTHENTICATED",
        "user_name": "Jorge Ramírez",
        "user_email": "jorge.ramirez@example.test",
        "status": "IN_ATTENTION",
        "channel": "WEB",
        "assigned_advisor_id": ANA_ID,
        "bot_enabled": False,
        "message_count": 4,
        "unread_count": 0,
        "wait_message_sent": False,
        "handoff_requested_at": _t("11:20:00"),
        "handoff_reason": "funds_claim",
        "last_message_preview": "Perfecto, quedo atento a tu confirmación.",
        "last_message_at": _t("11:48:00"),
        "created_at": _t("11:15:00"),
        "updated_at": _t("11:48:00"),
    },
    {
        "conversation_id": "conv_h04",
        "user_type": "ANONYMOUS",
        "status": "BOT_ATTENDING",
        "channel": "WEB",
        "bot_enabled": True,
        "message_count": 2,
        "unread_count": 0,
        "wait_message_sent": False,
        "last_message_preview": "La comisión del comprador es 10% + IGV sobre el precio final.",
        "last_message_at": _t("15:10:04"),
        "created_at": _t("15:10:00"),
        "updated_at": _t("15:10:04"),
    },
    {
        "conversation_id": "conv_h05",
        "user_id": "user_105",
        "user_type": "AUTHENTICATED",
        "user_name": "Lucía Paredes",
        "user_email": "lucia.paredes@example.test",
        "status": "BOT_ATTENDING",
        "channel": "WEB",
        "bot_enabled": True,
        "message_count": 2,
        "unread_count": 0,
        "wait_message_sent": False,
        "last_message_preview": "Para habilitarte necesitas saldo suficiente en tu billetera.",
        "last_message_at": _t("15:25:03"),
        "created_at": _t("15:25:00"),
        "updated_at": _t("15:25:03"),
    },
    {
        "conversation_id": "conv_h06",
        "user_id": "user_106",
        "user_type": "AUTHENTICATED",
        "user_name": "Pedro Castro",
        "user_email": "pedro.castro@example.test",
        "status": "CLOSED",
        "channel": "WEB",
        "assigned_advisor_id": ANA_ID,
        "bot_enabled": False,
        "message_count": 3,
        "unread_count": 0,
        "wait_message_sent": False,
        "handoff_requested_at": _t("09:10:00"),
        "handoff_reason": "advisor_request",
        "last_message_preview": "Listo, ya quedó resuelto. ¡Gracias!",
        "last_message_at": _t("09:55:00"),
        "closed_at": _t("10:00:00"),
        "closed_by": "ADVISOR",  # enum ADVISOR|AUTO — NO el advisor_id (eso es en Tickets)
        "created_at": _t("09:05:00"),
        "updated_at": _t("10:00:00"),
    },
]


def _msg(conv: str, hora: str, mid: str, sender: str, texto: str | None, **extra) -> dict:
    creado = _t(hora)
    item = {
        "conversation_id": conv,
        "message_key": f"{creado}#{mid}",
        "message_id": mid,
        "sender_type": sender,
        "message_type": extra.pop("message_type", "TEXT"),
        "status": "PROCESSED" if sender == "USER" else "DELIVERED",
        "created_at": creado,
    }
    if texto is not None:
        item["content"] = texto
    item.update(extra)
    return item


MESSAGES = [
    _msg("conv_h01", "13:35:00", "msg_h0101", "USER",
         "Adjudiqué un vehículo y no sé cómo pagarlo", client_message_id="cli-h0101"),
    _msg("conv_h01", "13:40:00", "msg_h0102", "SYSTEM", "HANDOFF_REQUESTED",
         message_type="SYSTEM", metadata={"reason": "advisor_request"}),
    _msg("conv_h01", "13:42:00", "msg_h0103", "USER",
         "Necesito ayuda con el pago de mi adjudicación", client_message_id="cli-h0103"),

    _msg("conv_h02", "14:00:00", "msg_h0201", "USER",
         "El auto llegó con una falla que no estaba en la ficha", client_message_id="cli-h0201"),
    _msg("conv_h02", "14:06:00", "msg_h0202", "USER",
         "¿Pueden revisar mi caso de garantía?", client_message_id="cli-h0202"),

    _msg("conv_h03", "11:15:00", "msg_h0301", "USER",
         "Mi vehículo adjudicado sigue sin aparecer en mi cuenta", client_message_id="cli-h0301"),
    _msg("conv_h03", "11:20:00", "msg_h0302", "SYSTEM", "ADVISOR_ASSIGNED",
         message_type="SYSTEM", sender_id=ANA_ID),
    _msg("conv_h03", "11:35:00", "msg_h0303", "ADVISOR",
         "Ya lo estoy revisando con el área de operaciones.", sender_id=ANA_ID),
    _msg("conv_h03", "11:48:00", "msg_h0304", "USER",
         "Perfecto, quedo atento a tu confirmación.", client_message_id="cli-h0304"),

    _msg("conv_h04", "15:10:00", "msg_h0401", "USER", "cuanto es la comision del comprador?",
         client_message_id="cli-h0401"),
    _msg("conv_h04", "15:10:04", "msg_h0402", "BOT",
         "La comisión del comprador es 10% + IGV sobre el precio final."),

    _msg("conv_h05", "15:25:00", "msg_h0501", "USER", "que necesito para habilitarme?",
         client_message_id="cli-h0501"),
    _msg("conv_h05", "15:25:03", "msg_h0502", "BOT",
         "Para habilitarte necesitas saldo suficiente en tu billetera."),

    _msg("conv_h06", "09:05:00", "msg_h0601", "USER", "quiero hablar con un asesor",
         client_message_id="cli-h0601"),
    _msg("conv_h06", "09:40:00", "msg_h0602", "ADVISOR",
         "Ya actualicé tus datos de contacto, revisa por favor.", sender_id=ANA_ID),
    _msg("conv_h06", "10:00:00", "msg_h0603", "SYSTEM", "CONVERSATION_CLOSED",
         message_type="SYSTEM", sender_id=ANA_ID),
]

TICKETS = [
    {
        "ticket_id": ticket_id_for_conversation("conv_h01"),
        "conversation_id": "conv_h01",
        "user_id": "user_101",
        "user_email": "diego.salazar@example.test",
        "status": "PENDING",
        "priority": "HIGH",  # dashboard: "1 de prioridad alta"
        "handoff_reason": "advisor_request",
        "description": "Duda sobre cómo pagar una adjudicación.",
        "created_at": _t("13:40:00"),
        "updated_at": _t("13:40:00"),
    },
    {
        "ticket_id": ticket_id_for_conversation("conv_h03"),
        "conversation_id": "conv_h03",
        "user_id": "user_103",
        "user_email": "jorge.ramirez@example.test",
        "status": "IN_PROGRESS",
        "assigned_advisor_id": ANA_ID,
        "handoff_reason": "funds_claim",
        "description": "Vehículo adjudicado no aparece en la cuenta.",
        "missing_data": ["placa_vehiculo"],  # dashboard: "Datos pendientes" de Ana
        "created_at": _t("11:20:00"),
        "assigned_at": _t("11:25:00"),
        "updated_at": _t("11:48:00"),
    },
    {
        "ticket_id": ticket_id_for_conversation("conv_h06"),
        "conversation_id": "conv_h06",
        "user_id": "user_106",
        "user_email": "pedro.castro@example.test",
        "status": "CLOSED",
        "assigned_advisor_id": ANA_ID,
        "handoff_reason": "advisor_request",
        "description": "Actualización de datos de contacto.",
        "resolution": "Se actualizaron correo y teléfono en la cuenta del usuario.",
        "closed_by": ANA_ID,  # en Tickets es el advisor_id real (dashboard: "Cerrados hoy")
        "created_at": _t("09:10:00"),
        "assigned_at": _t("09:15:00"),
        "updated_at": _t("10:00:00"),
        "closed_at": _t("10:00:00"),
    },
]


def _uso(conv: str, hora: str, eid: str, tipo: str, proveedor: str, modelo: str, **extra) -> dict:
    creado = _t(hora)
    item = {
        "conversation_id": conv,
        "execution_key": f"{creado}#{eid}",
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


AI_USAGE = [
    _uso("conv_h04", "15:10:01", "exec_h0401", "CLASSIFICATION", "GOOGLE",
         "gemini-3.5-flash-lite", message_id="msg_h0401", intent="FAQ",
         input_tokens=175, output_tokens=10, estimated_cost_usd=Decimal("0.000180"),
         latency_ms=380),
    _uso("conv_h04", "15:10:03", "exec_h0402", "RESPONSE", "GOOGLE", "gemini-3.6-flash",
         message_id="msg_h0401", intent="FAQ", input_tokens=1380, output_tokens=42,
         estimated_cost_usd=Decimal("0.002400"), latency_ms=1620,
         rag_used=True, rag_results_count=4),
    _uso("conv_h05", "15:25:01", "exec_h0501", "CLASSIFICATION", "GOOGLE",
         "gemini-3.5-flash-lite", message_id="msg_h0501", intent="FAQ",
         input_tokens=170, output_tokens=10, estimated_cost_usd=Decimal("0.000175"),
         latency_ms=360),
    _uso("conv_h05", "15:25:03", "exec_h0502", "RESPONSE", "GOOGLE", "gemini-3.6-flash",
         message_id="msg_h0501", intent="FAQ", input_tokens=1310, output_tokens=38,
         estimated_cost_usd=Decimal("0.002100"), latency_ms=1490,
         rag_used=True, rag_results_count=3),
]


def main() -> None:
    print(f"Cargando datos extra con fecha {DIA}...")
    dynamo = recurso_dynamo()
    t = nombres_de_tabla()
    for nombre_tabla, items in [
        (t["conversations"], CONVERSATIONS),
        (t["messages"], MESSAGES),
        (t["tickets"], TICKETS),
        (t["ai_usage"], AI_USAGE),
    ]:
        tabla = dynamo.Table(nombre_tabla)
        with tabla.batch_writer() as lote:
            for item in items:
                lote.put_item(Item=item)
        print(f"  {len(items):>2} items -> {nombre_tabla}")
    print("Listo.")


if __name__ == "__main__":
    main()
