"""tickets — handoff a humanos y tabla Tickets. Conversacion ≠ ticket (RB-005/006).

Duenio del flujo de derivacion: criterios (RF-022), recoleccion de datos previos (D-008),
correo obligatorio del anonimo (RF-003/D-019), creacion del ticket y su ciclo
PENDING → IN_PROGRESS → CLOSED. Puede importar `conversations` (el handoff cambia el estado
de la conversacion); nunca al reves.
"""
