"""Superficie publica del chat (widget embebido en VMC).

Cubrira (RF-001..014, RF-022, RF-040..042 — endpoints concretos POR DEFINIR):
- crear conversacion / cerrar (estados: BOT_ATTENDING, PENDING_ADVISOR, IN_ATTENTION, CLOSED)
- enviar mensaje (con client_message_id para idempotencia RF-038) → encola en SQS ai-jobs
  y responde 202 (T8)
- listar mensajes (polling del frontend — TD-001)
- solicitar handoff (correo obligatorio si anonimo — RF-003 / D-019)
- presigned URL de S3 para subir imagen (RF-042)

BLOQUEADO POR: D-001 (identidad VMC), D-002 (max convs), D-005 (guardrails), D-018 (sesion anonima).
"""

from fastapi import APIRouter

router = APIRouter(prefix="/chat", tags=["chat"])

# TODO: endpoints por definir — no implementar sin cerrar las decisiones listadas arriba.
