"""Flujo de handoff: validar datos requeridos, crear ticket, poner conversacion en
PENDING_ADVISOR (via conversations.service), apagar IA (duracion → D-007). La notificacion
Slack NO se envia aqui: la entrada que llama encola en `notifications` (RF-028).
"""

# TODO F5: implementar al cerrar D-007, D-008, D-017, D-019.
