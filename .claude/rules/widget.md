---
paths:
  - "widget/**"
---

# Widget

- Infra en `infra/`, app del asesor/dashboard en `frontend/` (Next.js), **widget del chat en
  `widget/`** (JS plano sin build, se embebe en VMC; `test.html` para probarlo). **`widget/
  subastin.js` es GENERADO** (2026-09-07): se edita `widget/src/*.js` y se regenera con
  `node widget/build.mjs`; los 14 fragmentos son partes del cuerpo de UNA IIFE (comparten el
  closure, no son módulos), por eso `node --check` corre sobre el bundle y no sobre las partes.
  El bundle se versiona para que VMC siga sirviendo un solo archivo sin build, y el CI verifica
  con `build.mjs --check` que no quedó viejo. Índice de fragmentos en `widget/README.md`.
  Todo el código nuevo sigue este layout. `widget/logo-voyager.svg`, `widget/animation.html` y
  `widget/Anima-Bot.json` son **fuentes de referencia, no assets servidos**: `subastin.js` trae
  el wordmark de VMC calcado del SVG, el avatar animado del bot es un puerto a Canvas/WebGPU del
  efecto "Liquid Orb" de `animation.html` (decisión de producto, Aaron 2026-08-31) y el Lottie de
  `Anima-Bot.json` se descartó a propósito (cargar su runtime era más pesado) — no borrar estos
  tres archivos ni "limpiarlos" por parecer sueltos, son la fuente de verdad visual.
