---
paths:
  - "frontend/**"
---

# Frontend (Next.js 16)

- `frontend/` usa **Next.js 16** (App Router, React 19, Tailwind v4): APIs y convenciones difieren
  del entrenamiento — consultar `frontend/node_modules/next/dist/docs/` antes de escribir código,
  como pide `frontend/AGENTS.md`. Se despliega fuera de CDK (TD-003). Las páginas de
  `src/app/advisor/` **sí están conectadas** a la API `/advisor` (`src/lib/api.ts`; en local con
  `ADVISOR_DEV_AUTH=1`); desde 2026-09-07 no queda ningún mock (`mock-data.ts` se borró), la
  paleta de estados vive en `src/lib/status-colors.ts` y `types.ts` es el espejo de
  `api/schemas.py` (mantenerlo a mano al cambiar un `*Out`). Falta la UI de tickets
  (`getTickets`/`patchTicket` en `api.ts` ya existen).
