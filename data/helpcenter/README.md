# `data/helpcenter/` — conocimiento del bot (RAG)

Aquí viven el Centro de Ayuda descargado y los chunks que se suben a Pinecone. **El contenido
no se versiona** (`.gitignore`): se regenera con un comando y ya es público en el sitio de VMC,
así que versionarlo solo duplicaría texto y ensuciaría cada diff. Este README sí se versiona.

## Los dos pasos

```powershell
python -m scripts.helpcenter_fetch      # descarga el sitio -> *.md + chunks.json (sin credenciales)
python -m scripts.helpcenter_upload     # sube chunks.json a Pinecone (necesita PINECONE_API_KEY)
```

`helpcenter_fetch` deja **un `.md` por artículo** para que una persona pueda leer exactamente
qué se va a indexar antes de subirlo, y un `chunks.json` que es lo que consume el upload.

Opciones útiles:

| Comando | Para qué |
|---|---|
| `helpcenter_fetch --limit 3` | Prueba rápida sin descargar los 22 artículos |
| `helpcenter_upload --verify "cuánto es la comisión"` | Sube y consulta; **imprime los scores**, que es como se calibra `RAG_MIN_SCORE` |
| `helpcenter_upload --replace` | Refresco completo: borra el namespace antes de subir |

## Por qué `--replace` importa

El upsert es aditivo. Si una pregunta del Centro de Ayuda cambia de redacción, su id cambia y
**el vector viejo se queda** en el índice respondiendo con contenido desactualizado. Para un
refresco completo hay que borrar el namespace primero.

Los ids son estables por diseño (`hc-<artículo>-<pregunta>-<huella>`, no `hc-1`, `hc-2`): así,
agregar una pregunta nueva no renombra las demás. Con ids posicionales, insertar una pregunta al
principio corre todas las siguientes y el upsert sobrescribe cada vector con el texto de otro
— sin que nada falle. La huella evita que dos preguntas largas que empiezan igual colisionen y
que una se pierda del índice en silencio.

## Cómo está indexado

- **Un chunk por pregunta**, más uno por la "Respuesta rápida" de cada artículo. El Centro de
  Ayuda ya está escrito como pares pregunta/respuesta: la unidad semántica existe en la fuente,
  y trocear por tamaño partiría respuestas a la mitad.
- Cada chunk lleva el **título del artículo** delante ("Comisión" a secas es ambiguo para el
  embedding) y su `source_url`, que es lo que permite citar la fuente en la respuesta (RF-019).
- El índice usa **embedding integrado** (`multilingual-e5-large` dentro de Pinecone). No se usa
  Gemini ni ningún otro modelo para embeber: la ingesta y la búsqueda usan el mismo modelo por
  construcción, que es el error clásico del RAG cuando se separan.
- Se descarta el ruido que se repite en todas las páginas (navegación, "Habla con nosotros", el
  widget de "¿Ha quedado contestada tu pregunta?"): indexarlo lo pondría a competir con el
  contenido real en cada búsqueda.

Última corrida de referencia: **22 artículos, 133 chunks**.

## Si el contenido viene de otro lado

`helpcenter_fetch` descarga de `centro-de-ayuda-vmc.vercel.app`. Para otra fuente, basta con
generar un `chunks.json` con la misma forma y correr solo el upload:

```json
{ "source": "...", "chunks": [
  { "id": "hc-tema-pregunta-a1b2c3", "text": "Título\nPregunta\nRespuesta",
    "topic": "Título del artículo", "source_url": "https://...", "has_numeric_data": true }
]}
```
