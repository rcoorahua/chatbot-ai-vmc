"""Piezas del pipeline IA del worker (`workers/ai_worker.py` es la ENTRADA: `handler`,
`_process`, `_attend`; aqui vive lo que compone).

Un modulo por preocupacion, con dependencias en un solo sentido (de arriba hacia abajo):

    trace       `ctx()`: el `extra` de cada log con conversation_id/message_id
    state       el flujo guiado en la fila de Conversations: vigente, vencido, limpiar, releer
    window      accesores PUROS sobre la ventana de contexto (rafaga, ultimo mensaje del bot,
                consulta previa, historial para el redactor)
    accounting  AIUsage: cada decision queda registrada, tambien las gratis (T-04)
    replies     toda respuesta del bot sale por aqui: fijas, login del anonimo, formulario,
                botones de un paso, pregunta de asesor, cuota agotada
    faq         RAG + redactor (RF-017/018) con continuidad (TD-009) y hermanas (D-030)
    guided      flujos guiados del corpus (D-028) y la confirmacion de asesor (D-029)

Antes todo esto era un solo archivo de 1.070 lineas con 33 funciones privadas (auditoria
2026-09-06). Los tests siguen entrando por `ai_worker._process`/`handler`.
"""
