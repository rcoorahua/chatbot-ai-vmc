---
name: commit
description: Aplica el flujo de git de Subastín — Trunk-Based Development y Conventional Commits con trazabilidad al spec. Usar SIEMPRE que se vaya a commitear, crear o mergear ramas, o cuando el usuario pida guardar, integrar o subir cambios, o mencione commit, branch, merge o PR.
---

# Git — Trunk-Based Development + Conventional Commits

## TBD adaptado — ramas y entornos

- **`develop` es el trunk de integración**: todos integran aquí frecuentemente vía PR, siempre
  estable (CI en verde antes de mergear). Push a develop → deploy a **stage** (cuando el CD
  esté activo).
- **`main` es producción**: protegida, solo recibe PRs desde develop (promoción/release).
  Push a main → deploy a **prod** con gate manual de reviewers.
- **Ramas de corta duración**: `feature/<slug>` o `fix/<slug>`, máximo 2–3 días, PR a develop.
  Nada de ramas eternas.
- **Commits pequeños y frecuentes**: una unidad lógica por commit; integración continua para
  evitar conflictos. Nada de mega-commits al final del día.
- Mapeo rama → entorno: `feature/`/`fix/` → solo CI · `develop` → stage · `main` → prod.
  dev es local (docker-compose), sin rama asociada.

## Conventional Commits

```
<type>[scope opcional]: <descripción>

[cuerpo opcional]

[footer(s) opcional(es)]
```

**Types**: `feat` (nueva funcionalidad) · `fix` (bug) · `chore` (mantenimiento) · `docs` ·
`style` (formato, sin lógica) · `refactor` (sin cambio funcional) · `test`.

**Scope** = módulo tocado: `conversations`, `tickets`, `advisors`, `agent`, `catalog`,
`notifications`, `images`, `api`, `workers`, `core`, `infra`, `frontend`, `skills`.

Reglas:
- Descripción en imperativo, minúscula inicial, sin punto final, ≤ 72 caracteres.
- **Trazabilidad spec-driven**: implementa un RF/AC → cuerpo con `Implementa RF-xxx / AC-xxx`;
  cierra decisión → `Cierra D-xxx` / `Cierra TD-xxx`.
- Breaking change: `!` tras type/scope + footer `BREAKING CHANGE: <detalle>`.
- Footer de coautoría de Claude según el harness (Co-Authored-By).

Ejemplos:

```
feat(conversations): mensaje fijo de espera una sola vez por periodo

Implementa RF-027 / AC-004.
```

```
test(agent): clasificador cubre intents FAQ/CATALOG/ADVISOR/OTHER
```

## Reglas de esta base

- El repo AÚN NO tiene commits: el primero incluye el esqueleto completo como
  `chore: esqueleto inicial del MVP (backend modular, infra CDK, frontend, skills)`.
- Jamás commitear `.env`, backups, `.venv/`, `node_modules/`, `__pycache__/` (ya en .gitignore).
- Commitear solo cuando el usuario lo pida (regla del harness); al hacerlo, aplicar todo lo
  anterior sin excepción.
