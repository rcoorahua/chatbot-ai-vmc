---
paths:
  - "backend/tickets/**"
  - "backend/api/routers/chat.py"
  - "backend/api/routers/advisor.py"
  - "frontend/**"
---

# Tickets

- **La taxonomía de tickets es una PROPUESTA, no la decisión.** D-008 sigue abierta y la
  cierran Silvana + Julio. Toda la taxonomía (los 12 `problem_type`, su categoría, su
  prioridad y sus datos mínimos) vive SOLO en `backend/tickets/taxonomy.py`, y el enum de
  Pydantic es lo único que la valida: cerrar D-008 con otra lista es editar ese archivo y sus
  tests, no rastrear literales por el backend. El `problem_type` que ponen las reglas es una
  sugerencia gratuita (sin modelo, no gasta cuota D-027); el ticket guarda en
  `classification_source` si lo decidió la regla o una persona, y esa corrección del asesor
  es la medida con la que se evaluará la propuesta antes de cerrarla. No copiar la lista al
  frontend: se lee de `GET /advisor/taxonomy`, que la publica con `proposal: true`.
- El ticket es 1:1 con la conversación escalada (D-029) y **nace en la entrada, no en el
  dominio**: `conversations` no puede importar `tickets` (regla de `backend/__init__.py`), así
  que quien compone "derivar + abrir ticket" es `api/routers/chat.py`. Si esa creación falla,
  el handoff NO se rompe (la conversación ya es durable y el usuario ya vio su confirmación):
  la red de seguridad es `tickets.ensure_ticket`, que corre cuando el asesor abre o toma el
  caso. Por eso ningún caso llega a la bandeja sin registro.
