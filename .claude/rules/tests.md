---
paths:
  - "tests/**"
---

# Suite de tests

Los tests corren contra **dynamodb-local real**, no mocks: si los contenedores no están arriba
se saltan en local, pero **fallan duro en CI** (`conftest.py` distingue por la variable `CI`).
De ahí que un GSI mal definido se detecte en `tests/test_dynamo_queries.py` y no en producción.

Convenciones de la suite (`tests/conftest.py`): `conftest` fija SIEMPRE los endpoints locales y
apunta `AWS_CONFIG_FILE` a `devnull` — un `.env` en blanco no puede convertir la suite en una
escritura a AWS real; también fija secretos de identidad de prueba, así que no necesita `.env`.
Los tests que **escriben** registran lo que crean en la fixture `limpiar` (un `Registro`:
`limpiar(conversation_id)`, `.asesor()`, `.ticket()`, `.limite()`; borra mensajes, AIUsage,
ticket y fila al terminar) y **nunca mutan el dataset de `seed_data`**, que es lo que
consultan las pruebas de lectura. **El andamiaje vive en `tests/helpers/` (desde
2026-09-07)** y no se copia por archivo: `fakes.py` (`FakeLLM` hereda de `LLMClient`,
`ExplodingLLM`, `install_llm`, dobles del RAG `fragmento`/`con_evidencia`/`sin_evidencia`/
`RagSpy`/`install_rag`, `FakeIndex` + `hit`), `scenario.py` (`conversacion`, `escribe`,
`atiende`, `respuestas_bot`, `fresca`, `usos_de`…: dominio + worker), `http.py`
(`abrir_sesion`, `enviar`, `pedir_handoff`, `asesor_nuevo`, `tomar`, `cerrar`…: API) y
`golden.py`; las fixtures (`fake_llm`, `sin_llm`, `sin_rag`, `con_rag`, `sin_rag_llamada`,
`cola_falsa`, `client`, `advisor_client`, `sin_rate_limit`, `settings_limpios`) están en
`conftest.py`. Antes de escribir un `_foo` en un archivo de tests, buscar ahí; si dos
archivos lo necesitan, va ahí. La suite corre sin claves ni red: nadie simula el SDK.
