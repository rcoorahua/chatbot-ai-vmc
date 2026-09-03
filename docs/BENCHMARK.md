# BENCHMARK.md — Benchmark de recuperación del FAQ

Mide **si el RAG le entrega al redactor la evidencia correcta** cuando la gente pregunta como
pregunta de verdad: paráfrasis, erratas, mensajes de dos palabras y preguntas que el corpus
**no** responde. Corre contra Pinecone real, **sin Gemini**, en un minuto, y da números
comparables entre versiones. Es lo que [TEST.md](TEST.md) no puede dar: esa guía prueba que el
pipeline está entero; esta mide si el FAQ es bueno.

- Spec: RF-017 (recuperación), RF-018 (umbral: sin evidencia no se responde), RB-009 (nunca
  inventar). Complementa a D-026 (eval de intents) en la capa de recuperación.
- Golden set: [`tests/golden/retrieval.jsonl`](../tests/golden/retrieval.jsonl) · script:
  [`scripts/eval_retrieval.py`](../scripts/eval_retrieval.py) · forma validada en CI por
  `tests/test_golden_retrieval.py` (la medición real no está en CI: necesita Pinecone).

---

## 1. Qué mide

Cada caso es una consulta **tal como llegaría al índice** y la lista de artículos que la
responden (vacía si ninguno). El script llama a `rag.retrieve()` por el mismo camino que el
worker (umbral `RAG_MIN_SCORE` + expansión por tema `RAG_SIBLING_MARGIN`) y juzga:

| Métrica | Sobre qué casos | Qué cuenta como acierto |
|---|---|---|
| **recall** | los que tienen respuesta (`parafrasis`, `errata`, `corta`, `canonica`) | entre la evidencia que vería el redactor hay al menos un fragmento del artículo correcto |
| **rechazo** | los que no la tienen (`sin_respuesta`, `ajena`) | cero evidencia. Un negativo que "se cuela" le da al redactor material para inventar |

Los dos se tensan entre sí: bajar el umbral sube recall y hunde rechazo. Por eso se miran
juntos y el script imprime además **por qué** falla cada positivo: `tema_equivocado` (pasó
otro artículo), `sin_evidencia` con el artículo **entre los candidatos** (problema del umbral)
o **ausente** de ellos (problema del embedding). Son arreglos distintos.

### Categorías del golden set

| kind | Casos | Qué representa |
|---|---|---|
| `parafrasis` | 77 | la pregunta dicha de otra forma, sin copiar el título. Cada uno de los 22 artículos tiene ≥ 2 |
| `canonica` | 6 | las consultas canónicas de los flujos de D-028 (lo que se busca al resolver un paso) |
| `errata` | 10 | lo que escribe alguien apurado en el celular: komision, bisita, regitro, contrasena |
| `corta` | 8 | una o dos palabras sin verbo: "comision", "precio reserva", "en vivo" |
| `sin_respuesta` | 8 | se parecen a un tema del corpus pero **nada** las responde ("¿pongo RUC o DNI?") |
| `ajena` | 12 | fuera de dominio: el dólar, una receta, el brevete, un poema |

Los casos `sin_respuesta` son los más valiosos y los más difíciles: para el embedding se
parecen a una pregunta legítima. Son exactamente el caso en que el bot debe decir "no tengo
ese dato" en vez de responder con lo que más se parezca.

---

## 2. Cómo correr

Requiere `PINECONE_API_KEY` en `.env` y el índice cargado (`python -m scripts.helpcenter_upload`).
No usa `GEMINI_API_KEY`; puedes correrlo con el worker levantado.

```powershell
python -m scripts.eval_retrieval                      # todo, con la config de .env
python -m scripts.eval_retrieval --only errata        # una categoría
python -m scripts.eval_retrieval --threshold 0.82     # probar otro RAG_MIN_SCORE sin tocar .env
python -m scripts.eval_retrieval --margin 0           # sin expansión por tema
python -m scripts.eval_retrieval --rerank             # experimental: reranker de Pinecone (§4)
python -m scripts.eval_retrieval --show-all --json corrida.json   # detalle por caso
```

Salida: cada fallo con su categoría, veredicto, mejor score y el score del artículo esperado;
luego una tabla por categoría y las dos métricas. Sale con código 1 si recall o rechazo quedan
por debajo de los **pisos** (`RECALL_FLOOR = 0.78`, `REJECT_FLOOR = 0.85`), fijados un poco
por debajo de la línea base: un caso nuevo difícil no lo rompe; recrear el índice con otro
modelo o mover el umbral a ciegas, sí.

**Cuándo correrlo:** al tocar el corpus (`helpcenter_fetch` / `upload`), al recrear el índice,
al cambiar `RAG_MIN_SCORE`, `RAG_SIBLING_MARGIN` o `RAG_TOP_K`, y al tocar `agent/rag.py`.
Antes y después, y pegar las dos tablas en el PR.

---

## 3. Línea base — 2026-09-03

Índice `subastin-rag/helpcenter`, `multilingual-e5-large` integrado, umbral **0.84**, margen
por tema **0.04**, `top_k` 4 (+4 de cantera). 121 casos.

| Categoría | Casos | OK | Tasa | Fallos |
|---|---|---|---|---|
| parafrasis | 77 | 68 | 88% | 6 sin evidencia, 3 tema equivocado |
| canonica | 6 | 6 | 100% | |
| errata | 10 | 6 | 60% | 4 sin evidencia |
| corta | 8 | 5 | 62% | 3 sin evidencia |
| sin_respuesta | 8 | 6 | 75% | 2 se cuelan |
| ajena | 12 | 12 | 100% | |
| **recall** | 101 | 85 | **84.2%** | 12 con el artículo entre los candidatos, 1 ausente |
| **rechazo** | 20 | 18 | **90.0%** | |

Lectura: el embedding **encuentra** el artículo casi siempre (solo 1 de 101 no aparece entre
los 8 candidatos); lo que falla es la **decisión** con el umbral. Y no hay umbral bueno:

| `RAG_MIN_SCORE` | recall ≈ | rechazo ≈ |
|---|---|---|
| 0.80 | 98% | 20% |
| 0.82 | 96% | 40% |
| 0.83 | 91% | 55% |
| **0.84** | **84%** | **90%** |
| 0.85 | 76% | 95% |

(Curva aproximada a partir de los scores de la corrida: acierto si el artículo esperado
supera el umbral, rechazo si el mejor candidato no lo supera.) Todo el corpus vive entre 0.78
y 0.88 de similitud, así que cada centésima mueve decenas de casos. Es la compresión típica de
`multilingual-e5-large` en textos cortos, ya anotada en CLAUDE.md al calibrar el 0.84.

### Los fallos, por causa

- **Vocabulario del usuario que el corpus no usa** (6): "garantía" por consignación, "me
  cobran" por comisión, "me inscribo" por registro, "debo plata" por deuda, "mi mecánico" por
  inspección. Ningún umbral los arregla: el embedding no sabe que en VMC son sinónimos.
- **Errata en la palabra clave** (4): komision, bisita, contrasena, comicion. Hunden los 4
  fragmentos a la vez, así que la expansión por tema no tiene de dónde agarrarse.
- **Una sola palabra** (3): "comision", "registro", "visitas" quedan a 0.01 del umbral.
- **Otro artículo pasa primero** (3): "gané la subasta y ahora qué hago" trae el artículo de
  *habilitado* (el paso siguiente) en vez del de *ganador*; son artículos vecinos y el
  redactor probablemente respondería bien igual, pero el benchmark lo cuenta como fallo.
- **Se cuelan** (2): "puedo cambiar el correo de mi cuenta" (entra el artículo de registro,
  con 2 hermanos por tema: el precio de la expansión) y "puedo vender mi auto en vmc" (0.863:
  *consignar* en el corpus es el depósito para pujar, pero en el habla del rubro es dejar el
  auto para venderlo). Este último es un riesgo real de respuesta equivocada.

### Casos que el benchmark confirma como correctos

- "¿En el formulario de registro pongo RUC o DNI?" → sin evidencia. **El corpus no menciona
  RUC**; la pregunta reescrita a mano de la forma más limpia posible da 0.834. Bajar el umbral
  no la arregla, la hace peor (§3, curva). Lo mejorable ahí es el tono de la respuesta, no la
  recuperación.
- "hola como me regitro" → 4 fragmentos, 2 por tema, con los pasos del registro.
- Las 6 consultas canónicas de los flujos: 100%.
- Las 12 ajenas: 100% rechazadas, incluida "escríbeme un poema sobre subastas".

---

## 4. Experimento: reranker en lugar del umbral (TD-010)

`--rerank` no cambia el pipeline: toma los 8 candidatos de e5 y los vuelve a puntuar con un
cross-encoder alojado en Pinecone (`bge-reranker-v2-m3`, `pc.inference.rerank`), que lee
pregunta y fragmento **juntos** y responde "¿esto contesta aquello?". Mismo proveedor, una
llamada más por consulta, cero Gemini. Medido el 2026-09-03 sobre los mismos 121 casos:

| Decisor | recall | rechazo | errata | corta | sin_respuesta |
|---|---|---|---|---|---|
| e5 ≥ 0.84 + tema 0.04 (hoy) | 84.2% | 90.0% | 60% | 62% | 75% |
| reranker ≥ 0.30 | 84.2% | 95.0% | 80% | 100% | 88% |
| **reranker ≥ 0.10** | **89.1%** | **95.0%** | 80% | 100% | 88% |

Curva del reranker (misma aproximación que arriba): 0.05 → 90/95, 0.10 → 89/95, 0.20 → 87/95,
0.30 → 84/95, 0.50 → 79/95. **El rechazo no se mueve** entre 0.05 y 0.50: los negativos
puntúan 0.000–0.023 salvo "vender mi auto" (0.655, el mismo caso ambiguo de *consignar*), y
los positivos que responden, 0.6–0.99. El score sí mide "responde o no", que es lo que el
umbral de e5 fingía medir.

**Lo que el reranker tampoco arregla**: los sinónimos del rubro (garantía, me cobran, me
inscribo, debo plata: 0.00–0.04) y la errata en la palabra clave (komision 0.043). Ninguno de
los dos modelos sabe vocabulario de VMC. Eso se arregla del lado del **corpus**, no del
decisor: indexar con cada fragmento **preguntas alternativas** escritas como las hace la gente
(la técnica estándar de "synthetic queries" en la ingesta; `helpcenter_fetch` ya separa
pregunta y respuesta, sería un campo más) y una corrección ortográfica contra el vocabulario
del corpus antes de buscar. Las dos son deterministas y gratis en runtime.

**Recomendación (pendiente de decidir, TD-010 en CLAUDE.md):** reranker con umbral 0.10 como
decisor de evidencia, e5 como prefiltro de 8 candidatos; `RAG_MIN_SCORE` pasa a ser un piso
flojo (≈ 0.75) que solo evita mandar basura al reranker. Sube recall 5 puntos y rechazo 5 sin
tocar el corpus, y desactiva la guerra de centésimas. Verificar antes: cuota del reranker en
el plan de Pinecone y su latencia real desde Lambda. Después, preguntas alternativas en la
ingesta para el vocabulario del rubro, y volver a correr esto.

---

## 5. Cómo mantener el golden set

- **Un caso por línea**, JSON: `query` (lo que se manda al índice), `kind`, `topics` (títulos
  **exactos** de los artículos que responden, con sus comillas tipográficas; varios si más de
  un artículo lo cubre, como la devolución de la consignación), `note` (por qué está).
- **Los negativos llevan `topics: []`**. No inventes negativos fáciles: los que valen son los
  que se parecen a un tema del corpus.
- **No copies el título del artículo** como paráfrasis (el test lo rechaza). Escríbelo como lo
  escribiría alguien que no leyó el Centro de Ayuda.
- Un caso que **falla** también sirve: documenta un límite conocido y avisa cuando se arregle
  (o cuando una "mejora" lo rompa). No lo borres para que el número suba.
- Al agregar un artículo al corpus: ≥ 2 paráfrasis y, si aplica, un `sin_respuesta` cercano.
  `tests/test_golden_retrieval.py` exige 22 artículos con ≥ 2 paráfrasis cada uno; si el
  corpus crece, subir `MIN_ARTICLES`.
- Los títulos se pueden copiar de `data/helpcenter/*.md` (primera línea) o del campo `topic`
  de la Consola IA.

## 6. Lo que este benchmark NO mide

- **La redacción**: que el bot, con la evidencia correcta, responda bien y en el tono de
  D-025. Eso se juzga con Gemini, a mano y de vez en cuando (20–30 conversaciones de TEST.md
  §3), porque cuesta cuota.
- **La conversación**: continuidad, flujos, formulario, casos. Es TEST.md §3 y los tests de
  `tests/test_ai_worker_*.py`.
- **La consulta que el sistema construye** a partir del historial (TD-009): aquí cada caso ya
  es la consulta final. Si un día el clasificador reescribe la pregunta, se agregan casos
  con la reescritura esperada.
- **El ruteo** (FAQ / OTHER / ADVISOR…): es `scripts.eval_intents` (D-026).
