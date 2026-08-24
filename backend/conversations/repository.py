"""UNICO lugar que conoce claves/GSIs de Conversations y Messages.

Operaciones previstas (PLAN.md §4):
- get/create/update conversacion; listar por usuario (GSI1), bandeja por estado (GSI2),
  por asesor (GSI3)
- guardar mensaje IDEMPOTENTE: TransactWriteItems con item marcador CMID#<client_message_id>
  y condicion attribute_not_exists (ajuste 4 — RF-038/RNF-004)
- toma atomica: UpdateItem condicional status=PENDING_ADVISOR AND
  attribute_not_exists(assigned_advisor_id) (AC-005)
- listar mensajes por SK (orden cronologico gratis)
"""

# TODO F1: implementar al arrancar. Limites/guardrails dependen de D-005.
