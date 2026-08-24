---
name: rag-architect
description: Diseño y evaluación del pipeline RAG de Subastín (FAQ sobre Pinecone, fase F3) — chunking guiado por el corpus real, evaluación de recuperación con métricas, y la regla de nunca inventar sin evidencia. Usar al diseñar o implementar la ingesta a Pinecone, agent/rag.py, elegir chunking o modelo de embeddings, o cuando se mencione RAG, retrieval, embeddings, chunks, Pinecone o precision/recall.
---

# RAG Architect (adaptado a Subastín)

El RAG de Subastín alimenta las respuestas FAQ (RF-017) desde conocimiento VMC en Pinecone.
Un diseño RAG sin números de evaluación es una hipótesis, no un entregable.

## Reglas duras

1. **RF-018 es el contrato central**: si la recuperación no da evidencia suficiente, el
   resultado es "insuficiente" y quien llama inicia handoff. El umbral de "suficiente" se define
   con datos (evaluación), no por intuición, y es configurable (§1.1) — nunca hardcodeado.
2. **Chunking guiado por el corpus real**: probar 2–3 estrategias (por secciones/headers, tamaño
   fijo con overlap, por párrafos) sobre los documentos VMC reales y comparar con la evaluación
   de abajo antes de fijar una. Mostrar chunks de muestra para sanity-check de fronteras.
3. **Fuente trazable**: cada chunk guarda metadata de origen (doc, sección, URL del centro de
   ayuda) — RF-019 exige incluir el enlace cuando exista.
4. **Nunca presentar modelos de embeddings o precios como hechos vigentes**: recomendar tier
   (rápido/balanceado/calidad API), nombrar un candidato y verificar contra la página del
   proveedor al implementar.

## Workflow (fase F3)

1. **Ingesta** (proceso NO definido en el spec — diseñarlo con el usuario antes de codear):
   qué documentos VMC entran, quién los cura, cómo se re-indexa al cambiar contenido.
2. **Golden set de consultas**: ≥20 preguntas reales (ideal: sacadas de Intercom) con los
   documentos que deberían recuperar; incluir preguntas SIN respuesta en el corpus (para probar
   RF-018) y casos borde, no solo happy path.
3. **Evaluar**: precision@k y recall@k contra el golden set (k=3,5). Piso inicial sugerido:
   precision@5 ≥ 0.8 — calibrar con el usuario. Además: tasa de "insuficiente" correcta sobre
   las preguntas sin respuesta (RF-018 no debe filtrar respuestas inventadas).
4. **Iterar UNA variable a la vez** (chunking → embeddings → top-k → umbral) y re-evaluar. El
   diseño está terminado solo cuando los números pasan el piso acordado.

## Registro por consulta

`agent/rag.py` reporta `rag_used` y `rag_results_count` para AIUsage — permite medir tasa de
recuperación pobre y fallbacks en producción (la evaluación no termina en F3).

## Fuera de esta skill

Costos de las llamadas → skill `llm-cost-optimizer`. Redacción/system prompts → skill
`prompt-governance`.
