---
name: prompt-governance
description: Gobierno de prompts de Subastín — los prompts son código versionado con golden dataset y evaluación antes de cambiar. Usar al crear o modificar cualquier prompt (agent/prompts.py), al evaluar si un cambio de prompt regresiona calidad, o cuando se mencione system prompt, prompt versioning, regresión de prompts o evals.
---

# Prompt Governance (adaptado a Subastín)

Los prompts cambian comportamiento en producción: se shipean como código. En Subastín el
registro es **git sobre `backend/agent/prompts.py`** (registry-lite: constantes puras,
versionadas, con rollback = `git revert`). RF-049 refuerza el modelo: los prompts NO son
editables desde la UI del MVP.

## Reglas duras

1. **Prompts solo en `agent/prompts.py`** — nunca hardcodeados inline en classifier/writer ni
   duplicados entre módulos. Cada prompt con comentario de propósito y qué RF sirve.
2. **Restricciones de negocio DENTRO del system prompt y verificadas por eval**: no exponer
   datos financieros/internos/de otros usuarios (RF-052), no inventar sin evidencia (RF-018),
   incluir fuente cuando exista (RF-019).
3. **Ningún cambio de prompt sin evaluación**: correr el golden dataset antes y después, y
   comparar. "Se ve mejor" no es evidencia. Cambio sin eval = apuesta — flaggearlo si el usuario
   quiere saltárselo "solo esta vez".
4. **Golden dataset por prompt**, versionado junto al prompt (en `tests/`): ≥20 ejemplos
   cubriendo casos borde y modos de fallo, no solo happy path.
   - Clasificador (Haiku): pares mensaje → intent esperado; piso: ≥95% exact match.
   - Redactor (Gemini): entradas con evidencia RAG → checks de contenido (contiene la fuente,
     no afirma datos fuera de la evidencia); LLM-as-judge solo si los checks no bastan.
5. **Eval en CI** (skill `ci-cd`): los evals del clasificador corren como tests (mocks no —
   estos SÍ necesitan modo eval real o fixtures grabadas; definir con el usuario el trade-off
   costo/señal antes de F2).

## Ciclo de cambio de prompt

```
rama corta → editar prompts.py → eval vs golden set → comparar score con el actual
→ PR con diff + delta de score → merge → monitorear AIUsage/handoff rate 24-48h
→ regresión detectada → git revert (rollback de un comando)
```

## Señales proactivas

- Prompt inline fuera de `prompts.py` → mover.
- Prompt cambiado sin actualizar su golden set → el golden set también se versiona.
- Tasa de handoff o de intent OTHER subiendo tras un cambio de prompt → sospechar regresión,
  comparar con la versión anterior.

## Fuera de esta skill

Costo/caching de las llamadas → `llm-cost-optimizer`. Recuperación/chunks → `rag-architect`.
