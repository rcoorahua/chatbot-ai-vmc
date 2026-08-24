"""Orquestacion del dominio conversacion (SIN llamar integraciones — regla de backend/__init__.py).

Previsto: crear conversacion (max activas → D-002/D-018), registrar mensaje entrante + encolar
job IA, ventana de ~20 mensajes para IA (RF-013, resumen → D-004), transiciones de estado,
mensaje fijo de espera una sola vez (RF-027), cierre (D-003).
"""

# TODO F1: implementar al arrancar. Bloqueos: D-002, D-003, D-005, D-018.
