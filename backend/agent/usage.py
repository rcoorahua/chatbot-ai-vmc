"""UNICO lugar que conoce claves/GSI de AIUsage (PK conversation_id, SK created_at#execution_id;
GSI billing_month). Cada llamada a Haiku/Gemini registra: tokens, costo estimado, latencia,
intent, rag_used, handoff_triggered (PLAN.md §4). Se alimenta desde F2; NO se expone en el
dashboard del MVP (RF-049).
"""

# TODO F2: implementar junto con classifier/writer.
