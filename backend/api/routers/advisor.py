"""Superficie del asesor (CAM). Autenticada con Cognito via JWT authorizer del HTTP API (T1).

Cubrira (RF-012, RF-029..039 — endpoints concretos POR DEFINIR):
- bandeja: pendientes/en atencion (GSI2 status + last_message_at), contador no leidos (RF-035)
- tomar conversacion: UpdateItem condicional para asignacion atomica (AC-005)
- ver hilo + contexto del usuario (campos visibles → D-010)
- enviar mensaje de texto (idempotente — RF-037/038)
- tickets (taxonomia → D-008; relacion conv↔ticket → D-017)
- cerrar caso (RF-031)

BLOQUEADO POR: D-007, D-008, D-010, D-017.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/advisor", tags=["advisor"])

# TODO: endpoints por definir — no implementar sin cerrar las decisiones listadas arriba.
