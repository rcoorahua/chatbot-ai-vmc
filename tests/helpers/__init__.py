"""Andamiaje compartido por la suite. UN solo lugar para lo que antes se copiaba por archivo.

- `fakes`     dobles del modelo (LLM) y del indice (RAG / Pinecone)
- `scenario`  escenario a nivel de dominio + worker: abrir conversacion, escribir, atender
- `http`      escenario a nivel de API: sesion del widget, mensajes, asesor, handoff
- `golden`    lectura de los golden sets (`tests/golden/*.jsonl`)

Las fixtures que usan estos helpers viven en `tests/conftest.py` (`limpiar`, `fake_llm`,
`sin_rag`, `con_rag`, `client`, `advisor_client`, `sin_rate_limit`...). Antes de escribir un
helper `_foo` en un archivo de tests, buscar aqui: si dos archivos lo necesitan, va aqui.
"""
