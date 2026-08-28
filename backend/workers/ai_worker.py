"""Lambda `worker-ai` — consumidor de SQS `ai-jobs`. Pipeline IA completo (T3/T8).

Por cada job (ESQUELETO — no implementar sin revisar CLAUDE.md):
 1. debounce/agregacion de mensajes consecutivos            → D-020
 2. filtro de saludos/spam/triviales sin llamada IA         → D-006
 3. clasificar intencion (`agent.classifier`, Gemini flash-lite por TD-008; Haiku es el plan B):
    FAQ | CATALOG | ADVISOR | OTHER (RF-015/016)
 4. FAQ      → RAG en Pinecone; sin evidencia = handoff, nunca inventar (RF-017/018),
               incluir fuente/enlace si existe (RF-019)
    CATALOGO → API HERALD (RF-044; contrato D-011, fallback D-012)
    ASESOR   → iniciar handoff (RF-022)
 5. redactar respuesta (`agent.writer`, RF-020) con `conversations.service.context_window`:
    los ultimos 20 mensajes de la ultima hora (RF-013 / D-004 cerrada 2026-08-28). NO hay
    resumen acumulado; si la ventana sale vacia, se responde solo al mensaje nuevo
 6. persistir respuesta en Messages + actualizar Conversations
 7. registrar ejecucion en AIUsage (tokens, costo, latencia, rag_used, handoff_triggered)
 8. si handoff: crear ticket segun D-008/D-019 y encolar notificacion Slack (RF-028)

Timeout largo y memoria propia (distintos de la Lambda api). visibility_timeout de la cola ≥ 6x
el timeout de esta funcion.
"""


def handler(event: dict, context) -> dict:
    failures: list[dict[str, str]] = []
    for record in event["Records"]:
        try:
            _process(record["body"])
        except Exception:  # noqa: BLE001 — el fallo de un mensaje no debe tumbar el batch
            failures.append({"itemIdentifier": record["messageId"]})
    # Formato exacto requerido por SQS partial batch response; si difiere, SQS lo ignora.
    return {"batchItemFailures": failures}


def _process(body: str) -> None:
    # TODO: pipeline descrito arriba. NO implementar sin cerrar D-004/D-006/D-020.
    #
    # El body es lo que encola api/routers/chat.py: validarlo con `core.jobs.AIJob` antes de
    # usarlo (regla 6 de security-guidance). Anonimo = solo FAQ (D-002): si la conversacion es
    # ANONYMOUS y la intencion es ADVISOR, se responde con texto fijo invitando a iniciar
    # sesion; no se crea ticket.
    #
    # Piezas ya disponibles para componer aqui (TD-008: Gemini atiende ambas etapas):
    #   agent.classifier.classify(mensaje, ultimo_mensaje_del_asistente) -> ClassificationResult
    #   agent.rag.search(mensaje) -> list[Fragment]  ·  agent.rag.as_context(fragmentos)
    #   agent.writer.write_answer(mensaje, fragmentos, historial)        -> WriterResult
    #
    # Al conectarlas, dos contratos que no son opcionales:
    #   - `WriterResult.has_evidence == False` significa handoff (RF-018), no reintento.
    #   - Cada resultado trae `usage`, `model` y `latency_ms` para AIUsage; el `source` del
    #     clasificador ("rules" | "model" | "fallback") mide cuanto trafico ahorran las reglas.
    #
    # TODO D-008: subtipo de escalacion para elegir el mensaje de espera y clasificar el ticket.
    # El proyecto de referencia distinguia nueve (legal_threat, live_auction, legal_vehicle,
    # frustrated, pre_abandonment, confusion, b2b, doubt, direct_simple) con un mensaje propio
    # por subtipo. `ClassificationResult.rule` ya nombra el motivo cuando decide una regla
    # (legal_threat, funds_claim, bot_rejection...) y es el insumo natural para esa taxonomia,
    # pero los tipos definitivos y sus campos obligatorios los cierran Silvana + Julio.
    raise NotImplementedError
