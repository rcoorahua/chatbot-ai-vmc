# Estado por fase (detalle)

Movido desde `CLAUDE.md` el 2026-11-20. Fuente de las fases: PLAN.md §8.

- Estado por fase: **F1 (chat + identidad + persistencia) implementada** —
  `core/{config,aws,auth,clock,jobs}.py`, `conversations/*`, `api/routers/chat.py`, `widget/`.
  **Mensajería del asesor implementada** (adelanto de F5, 2026-08-27): `advisors/*`,
  `api/routers/advisor.py`, `api/dev_auth.py`; falta el módulo `tickets` (D-008).
  **Pipeline IA implementado (F2+F3, 2026-08-28)**: `workers/ai_worker.py` (la entrada; desde 2026-09-07 las piezas viven en `workers/ai/`: `trace`, `state`, `window`, `accounting`, `replies`, `faq`, `guided`, con dependencias en un sentido) compone debounce
  (D-020) → triviales (D-006) → clasificador (reglas→Gemini, TD-008) → RAG/redacción → handoff
  mínimo, con registro en `AIUsage` (`agent/usage.py`); el bot responde (local:
  `scripts/run_ai_worker.py`). **Guardrails y golden set (D-024..D-026, 2026-08-28)**:
  `agent/guardrails.py` (entrada y salida), `tests/golden/intents.jsonl`, `scripts/eval_intents.py`.
  `RAG_MIN_SCORE` calibrado en `0.84` (2026-08-28, ver "RAG" abajo). **Casos y handoff con
  formulario (D-029, 2026-09-02)**: `conversations/forms.py`, `POST /chat/…/handoff`,
  `GET /chat/conversations`, lista y tarjeta en el widget. **Módulo `tickets` implementado
  (2026-09-02)**: `tickets/taxonomy.py` (⚠️ propuesta de Aaron para D-008, que sigue abierta),
  `tickets/{models,repository,service}.py`, y en `/advisor`: `GET /taxonomy`, `GET /tickets`,
  `GET /conversations/{id}/ticket`, `PATCH /tickets/{id}` y el cierre con resolución. Falta
  correr la eval real de intents y anotar el score base, y la notificación Slack (D-016).
  El resto (`catalog`,
  `images`, `notifications`, `routers/dashboard.py`, `workers/notify_worker.py`) son stubs con
  docstrings que indican qué D-xxx los bloquea; se implementan fase por fase (PLAN.md §8) cuando
  el usuario lo pida, no por adelantado.
