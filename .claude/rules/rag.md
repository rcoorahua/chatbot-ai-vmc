---
paths:
  - "backend/agent/**"
  - "backend/workers/**"
  - "scripts/helpcenter_*.py"
  - "scripts/eval_retrieval.py"
  - "docs/BENCHMARK.md"
---

# RAG y recuperación

- **Lo que se BUSCA en el RAG no siempre es lo que el usuario escribió** (`agent/followups.py`,
  2026-09-02; **TD-009 cerrada con D-030 el 2026-09-03**: el redactor ya responde completo y
  no promete pasos, así que esto queda como red de seguridad para continuaciones espontáneas
  del usuario). Hasta entonces el prompt prometía continuidad ("un paso a la vez, pregunta si
  continuar") y la recuperación era de un solo
  turno: "Ya estoy ahí" no se parece a nada del corpus, así que un usuario a mitad de una
  explicación terminaba derivado por "falta de evidencia" **con el artículo correcto entre los
  descartados** (0.789 contra el umbral 0.84, medido en el índice real). Ahora, si el mensaje es
  una continuación, la consulta pasa a ser **la pregunta previa del usuario, SOLA**. Tres cosas
  que costó aprender y conviene no re-descubrir:
  1. **No se le pega el texto del seguimiento.** Medido: `"Hola como me registro"` recupera 4/4
     con 0.859, y `"Hola como me registro sí"` solo 1/4 con 0.841. Las palabras de un acuse no
     describen nada del corpus y dispersan el embedding. Una continuación no cambia el tema, así
     que tampoco debe cambiar la evidencia; lo que cambia es lo que el REDACTOR dice sobre ella,
     y para eso recibe el texto original más el historial.
  2. **El emoji final no puede esconder la pregunta.** D-025 permite un emoji al cierre, así que
     casi toda pregunta real del bot llega como "¿…el siguiente paso? 🚚" y un `endswith("?")` a
     secas daba False: la regla de "responde a lo que preguntó el bot" no se activaba nunca.
  3. **Una pregunta con botones NO abre turno de tema.** Si el último mensaje del bot lleva
     `interaction` (quick replies, sí/no del asesor, formulario), lo que el usuario escriba y no
     la responda es un tema NUEVO. Sin esto, "mejor dime cuánto es la comisión" escrito tras
     "¿quieres un asesor?" heredaba el tema viejo y buscaba la pregunta equivocada.
  4. **(2026-09-03) La continuidad se decide ANTES de triviales y repetidos, y la consulta
     viaja con la respuesta.** En una explicación por pasos el usuario contesta "sí" varias
     veces: el segundo "sí" caía como *mensaje repetido* (D-006) y el tercero en silencio; y
     "ok"/"listo" tras una pregunta del bot caían como el "¡Con gusto!" de cierre. Ahora
     `_attend` calcula `is_continuation` primero y solo un acuse sin pregunta abierta es
     cierre. Además, cada respuesta con evidencia guarda en su metadata la consulta que la
     produjo (`followups.RAG_QUERY_KEY`) y una continuación busca con ESA consulta: así el
     "sí" tras un paso de flujo (D-028) repite la consulta canónica y no el texto del botón.
     "sí"/"listo"/"y luego?" ya no llaman al clasificador (`continuation:<regla>` en
     AIUsage, sin modelo). Medido: "quiero registrarme" 4/4 (0.858) contra "si" 0/4 (0.790).
     Tests: `tests/test_ai_worker_continuity.py`.

  Todo por reglas deterministas, sin llamada a modelo (no gasta cuota D-027). **No confundir con
  D-028**: `flows.py` es estado persistido con botones; esto solo cambia la consulta y no guarda
  nada.
- **RAG**: el índice de Pinecone usa **embedding integrado** (`multilingual-e5-large` dentro de
  Pinecone). Ingesta y consulta embeben con el mismo modelo por construcción; crear el índice a
  mano con otro modelo no da error, solo resultados malos. Por eso lo crea
  `scripts/helpcenter_upload.py`, no la consola web. Gemini **no** interviene en los embeddings.
- `RAG_MIN_SCORE` es RF-018 hecho código: Pinecone siempre devuelve los `top_k` más cercanos,
  también para una pregunta ajena al Centro de Ayuda. **Calibrado 2026-08-28 en `0.84`**
  (antes `0.75`, sin calibrar) contra el índice real: con `0.75`, preguntas totalmente ajenas a
  VMC ("¿cuánto está el dólar hoy?" → `0.835`, "receta de pastel" → `0.807`) pasaban el umbral
  y el redactor podía recibir evidencia que no venía al caso. El margen real es **angosto**
  (10 preguntas on-topic: mínimo `0.844`; 10 off-topic: máximo `0.835` — solo `0.009` de
  separación) por la compresión de similitud típica de `multilingual-e5-large` en textos
  cortos: ningún umbral separa perfectamente, y `0.84` es el mejor punto dentro de esa
  ventana con esta muestra, no un valor definitivo. Por eso la clasificación (ruteo a `OTHER`,
  RF-016) sigue siendo la primera defensa contra preguntas fuera de dominio; `RAG_MIN_SCORE`
  es el respaldo para cuando el clasificador falla o Gemini no responde (`classify()` cae a
  `FAQ` ante un `LLMError`). Re-verificar con `python -m scripts.eval_retrieval` (BENCHMARK.md;
  `--threshold X` prueba otro umbral sin tocar `.env`) si el corpus crece o si `RB-009` falla en
  producción. **Medido el 2026-09-03 sobre 121 casos: no hay umbral bueno** (0.83 → recall
  91% / rechazo 55%; 0.84 → 84 / 90; 0.85 → 76 / 95). La salida real es TD-010.
- **Expansión por tema (2026-09-03, `RAG_SIBLING_MARGIN=0.04`)**: el umbral decide solo si
  HAY evidencia; con un fragmento por encima, los del **mismo artículo** hasta 0.04 por debajo
  entran también (marcados `sibling` en AIUsage y "por tema" en la consola), hasta llenar
  `RAG_TOP_K`; se piden `top_k + 4` hits como cantera. Es el patrón *parent document /
  small-to-big*. Motivo: "hola como me **regitro**" dejó sobre el umbral dos fragmentos del
  artículo de registro que no explicaban el registro y a 0.006 por debajo el que sí; el bot
  preguntó "¿ya tienes cuenta?". Un fragmento de OTRO artículo sigue fuera aunque esté a un
  pelo: no baja el umbral, no deja entrar temas ajenos.
- Los ids de chunk son estables (`hc-<artículo>-<pregunta>-<huella>`): con ids posicionales, una
  pregunta nueva corre a todas las siguientes y el upsert sobrescribe cada vector con el texto de
  otro, sin fallar. El upsert es aditivo: para un refresco completo, `--replace`.
