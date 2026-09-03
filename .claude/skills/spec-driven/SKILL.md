---
name: spec-driven
description: Aplica la metodología Spec-Driven de Subastín — mapea cada cambio a RF/AC/RB de REQUERIMENTS.md, verifica decisiones abiertas (D-xxx/TD-xxx), exige criterio de aceptación antes del código y controla el alcance. Usar SIEMPRE antes de implementar, modificar o diseñar cualquier funcionalidad del MVP, al planear una fase, al escribir criterios de aceptación, o cuando aparezcan las palabras spec, requerimiento, RF, AC, RB, D-xxx o alcance.
---

# Metodología Spec-Driven

Fuente de verdad funcional: [REQUERIMENTS.md](../../../docs/REQUERIMENTS.md) (RF/RNF/RB/AC/D + modelo
DynamoDB). PLAN.md la traduce a arquitectura; CLAUDE.md registra el estado de las decisiones.

**Ley de hierro (adaptada):** sin mapeo a spec no hay código. Lo que no está en REQUERIMENTS.md
no se construye; si hace falta, primero se actualiza el spec (con el usuario), después se codea.

## Protocolo ANTES de implementar

1. **Mapear**: ¿qué RF/RB/AC cubre el cambio? Sin mapeo → preguntar si es alcance nuevo. Si está
   en §7 (fuera de alcance) → avisar y no implementar.
2. **Bloqueos**: si depende de una D-xxx/TD-xxx abierta (CLAUDE.md) → DETENERSE y avisar.
3. **Criterio primero**: enunciar el AC existente (§8) o derivar un Given/When/Then del RF ANTES
   de codear. Ese criterio se convierte en test (skill `testing`).
4. **RNF siempre activos**: idempotencia (RNF-004), identidad no confiable desde frontend
   (RNF-005), límites/TTL configurables jamás hardcodeados (RNF-007 + §1.1).

## Autonomía acotada — cuándo parar vs continuar

**PARAR y preguntar cuando:**
- La implementación pide algo que no está en el spec (aunque parezca obvio — pudo excluirse a propósito).
- No puedes determinar el comportamiento correcto desde el spec (ambigüedad real, no pereza).
- Tocas contrato de API existente, esquema DynamoDB con datos, o cualquier cosa de auth/identidad/PII.
- El cambio depende de VMC, HERALD u otro equipo externo sin contrato confirmado (D-001/D-011).

**CONTINUAR solo cuando:** el AC es claro y el cambio es traducción directa; o es refactor
interno con todos los tests en verde y sin cambios de comportamiento/contrato.

**Formato de escalación** (nunca preguntar en abierto, siempre con recomendación):

```
Bloqueado en: [RF-xxx / D-xxx]
Pregunta: [específica y respondible]
Opciones: A) [pros/contras]  B) [pros/contras]
Recomendación: [A o B, con razón]  ·  Impacto de esperar: [qué se bloquea]
```

## Protocolo AL TERMINAR

- **Trazabilidad**: RF/AC referenciado en el docstring y en el commit (`Implementa RF-027 / AC-004`).
- Vacío del spec descubierto → registrarlo (TD-xxx nueva o pregunta), jamás supuesto silencioso.
- Decisión cerrada en la conversación → CLAUDE.md (a cerradas) + PLAN.md + delta en REQUERIMENTS.md.

## Anti-patrones (rechazar al detectarlos)

| Anti-patrón | Regla |
|---|---|
| "Codeo mientras se decide D-xxx" | La implementación no empieza con la decisión abierta |
| AC vago ("debe funcionar bien") | Si no se puede escribir un test, se reescribe el criterio |
| Spec post-hoc ("documento lo que hice") | Eso es documentación, no spec; el orden es spec → código |
| Gold-plating ("ya que estaba, agregué…") | Lo no especificado se quita o se especifica primero |
| AC huérfano (sin RF que lo respalde) | Todo AC referencia al menos un RF/RNF |

## DoD por feature

RF cubierto con test de su criterio · sin decisiones abiertas como dependencia · suite en verde
(skill `testing`) · docs/decisiones al día · commit convencional (skill `commit`). DoD global: §9.
