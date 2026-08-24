"""conversations — EL CORAZON del dominio (heredero directo de `conversaciones` de la v0).

Duenio de las tablas Conversations y Messages. Todo lo que sea conversacion/mensaje pasa por
aqui: estados (BOT_ATTENDING → PENDING_ADVISOR → IN_ATTENTION → CLOSED), idempotencia,
unread_count, wait_message_sent, ventana de contexto para IA, auditoria como mensajes SYSTEM.
No importa a ningun otro modulo de dominio ni integracion — solo core.
"""
