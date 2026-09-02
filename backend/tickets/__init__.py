"""tickets — registro operativo del caso escalado. Conversacion ≠ ticket (RB-005/006).

Con D-029 (2026-09-02) el handoff en si lo hace `conversations` (el formulario crea el caso o
deriva la conversacion anonima); este modulo es el **registro de trabajo** de ese caso: de que
tipo es, que categoria, que prioridad, que datos minimos faltan (RF-024) y como se resolvio.
Ciclo PENDING → IN_PROGRESS → CLOSED, pegado al de la conversacion escalada.

- `taxonomy.py` — los 12 `problem_type` del corpus (MAPEO.md §8) + reglas por palabras clave.
  ⚠️ **PROPUESTA de Aaron: D-008 sigue ABIERTA** (la cierran Silvana + Julio). Toda la
  taxonomia vive ahi: cerrar la decision con otra lista es editar UN archivo.
- `service.py` — abrir, asignar, reclasificar y cerrar.

Puede importar `conversations`; `conversations` NUNCA importa `tickets`, asi que quien compone
"derivar + abrir ticket" es la entrada (`api/routers/chat.py`).
"""
