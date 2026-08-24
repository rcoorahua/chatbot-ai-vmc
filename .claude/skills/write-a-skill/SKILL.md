---
name: write-a-skill
description: Guía para crear o modificar skills de este repo con estructura correcta, descripciones que disparan bien y menos de 100 líneas. Usar cuando el usuario pida crear, escribir o mejorar una skill, o al agregar una skill nueva a .claude/skills/.
---

# Write a Skill (adaptado de Matt Pocock, MIT)

## Proceso

1. **Requisitos**: ¿qué tarea cubre? ¿casos de uso concretos? ¿necesita scripts o solo
   instrucciones? ¿referencias?
2. **Borrador**: SKILL.md conciso; archivos de referencia solo si el contenido lo exige.
3. **Revisión con el usuario**: ¿cubre los casos? ¿algo sobra o falta?

## La descripción lo es todo

Es lo ÚNICO que el agente ve para decidir si cargar la skill. Formato: tercera persona, primera
oración = qué hace, segunda = "Usar cuando [triggers específicos: palabras clave, archivos,
contextos]". Máximo 1024 caracteres.

- ✅ `Disciplina de testing de Subastín — corre la suite completa y aplica la barra de calidad.
  Usar después de CADA implementación de backend o cuando se mencione pytest, QA o cobertura.`
- ❌ `Ayuda con los tests.`

## Reglas de estructura

- **SKILL.md < 100 líneas.** Si crece: dividir en referencias un nivel de profundidad
  (`references/x.md`) y dejar en SKILL.md solo el flujo principal.
- Ejemplos concretos > descripciones abstractas (comandos reales, formatos reales).
- Nada sensible al tiempo (precios, versiones "actuales" sin fecha) — envejece mal.
- Scripts solo para operaciones determinísticas que se repetirían (validación, formato).
- Terminología consistente con el repo: RF/AC/D-xxx/TD-xxx, nombres de módulos reales.

## Convenciones de ESTE repo

- Ubicación: `.claude/skills/<nombre>/SKILL.md`; nombre en kebab-case, corto.
- Idioma: español (como los docs); triggers de la descripción pueden mezclar español/inglés.
- Cada skill se registra en la sección "Metodología" de CLAUDE.md y respeta a las demás
  (referencias cruzadas explícitas: "Fuera de esta skill → skill X").
- Skill de terceros: pasa por la skill `skill-auditor` ANTES de adaptarse; documentar origen,
  licencia y modificaciones.

## Checklist final

- [ ] Descripción con triggers ("Usar cuando…") y en tercera persona
- [ ] SKILL.md < 100 líneas, ejemplos concretos, sin info que caduque
- [ ] Sin solaparse con otra skill (si se solapa: fusionar, no duplicar)
- [ ] Registrada en CLAUDE.md
