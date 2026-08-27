"""Clasificacion de intencion (RF-015/016): reglas deterministas primero, Haiku despues.

Etapa 1 — `backend.agent.heuristics.classify_by_rules`: resuelve sin llamada IA los mensajes
inequivocos (ADVISOR / CATALOG) y calcula `frustration_hint` para la etapa 2.
Etapa 2 — Haiku `claude-haiku-4-5` (SDK `anthropic`) para el resto: FAQ | CATALOG | ADVISOR |
OTHER. Consultas de datos personales no habilitados -> ADVISOR (RF-016). El acceso al modelo
(API directa vs Bedrock) es TD-002 y bloquea solo esta etapa.
"""

# TODO F2: etapa 2 (llamada a Haiku) al cerrar TD-002.
