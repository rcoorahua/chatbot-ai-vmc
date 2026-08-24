---
name: commit
description: Flujo de git de Subastín — protocolo completo de implementación (pull develop → rama feature/fix → implementar → tests → PR a develop), Trunk-Based Development adaptado y Conventional Commits con trazabilidad al spec. Usar SIEMPRE que el usuario diga "implementa", "toca pushear", "sube esto", "haz merge", o mencione commit, branch, rama, PR, push o release.
---

# Git — flujo de implementación, TBD adaptado y Conventional Commits

Remoto: `https://github.com/rcoorahua/chatbot-ai-vmc`. Ramas: `main` (producción, protegida) ·
`develop` (trunk de integración, deploy → stage) · `feature/*` y `fix/*` (≤ 2–3 días).

## Protocolo cuando el usuario dice "implementa X" o "toca pushear"

1. **Sincronizar**: `git checkout develop && git pull origin develop`. Nunca partir de una rama
   vieja ni de main.
2. **Rama nueva** según el tipo de trabajo: `feature/<slug>` (funcionalidad), `fix/<slug>` (bug),
   `chore/<slug>` o `docs/<slug>` (mantenimiento/docs). Slug corto en kebab-case, ej.
   `feature/chat-enviar-mensaje`.
3. **Antes de codear**: skill `spec-driven` (mapear a RF/AC, verificar D/TD abiertas, criterio
   de aceptación primero). Si hay bloqueo → parar y avisar, sin crear nada más.
4. **Implementar** en commits pequeños y frecuentes (formato de abajo).
5. **Tests**: skill `testing` — escribir los tests del criterio de aceptación, correr la suite
   COMPLETA (`ruff check .` + `python -m pytest -q`) y no seguir hasta verde.
6. **Push de la rama**: `git push -u origin <rama>`.
7. **PR a develop** (nunca push directo a develop/main): sin `gh` CLI, abrir
   `https://github.com/rcoorahua/chatbot-ai-vmc/compare/develop...<rama>?expand=1`. Título = el
   commit principal; cuerpo = RF/AC cubiertos + qué se probó. El CI debe quedar en verde.
8. **Merge** (cuando el usuario lo pida y el CI esté verde): squash-and-merge si la rama tiene
   commits WIP, merge normal si cada commit es limpio; borrar la rama; volver a `develop` y
   `git pull`.
9. **Release a prod**: PR `develop → main` con título `release: <resumen>`; el deploy a prod
   tiene gate manual (skill `deploy`).

## Conventional Commits

```
<type>[scope opcional]: <descripción>

[cuerpo opcional]

[footer(s) opcional(es)]
```

**Types**: `feat` · `fix` · `chore` · `docs` · `style` · `refactor` · `test`.
**Scope** = módulo: `conversations`, `tickets`, `advisors`, `agent`, `catalog`, `notifications`,
`images`, `api`, `workers`, `core`, `infra`, `frontend`, `skills`, `ci`.

- Descripción en imperativo, minúscula inicial, sin punto final, ≤ 72 caracteres.
- Trazabilidad spec-driven en el cuerpo: `Implementa RF-xxx / AC-xxx` · `Cierra D-xxx`.
- Breaking change: `!` tras type/scope + footer `BREAKING CHANGE: <detalle>`.
- Footer de coautoría de Claude según el harness (Co-Authored-By).

Ejemplo:

```
feat(conversations): mensaje fijo de espera una sola vez por periodo

Implementa RF-027 / AC-004.
```

## Reglas de esta base

- Commitear/pushear solo cuando el usuario lo pida; al hacerlo, este protocolo completo.
- Jamás commitear `.env`, tokens, backups, `.venv/`, `node_modules/`, `__pycache__/`.
- Tokens de GitHub: nunca en el chat, en la URL del remoto ni en archivos; el usuario los usa
  desde su credential manager. Si un push falla por auth, dar el comando para que lo corra él.
- Ramas de más de 3 días: avisar y proponer partirlas; nada de ramas eternas.
- Mapeo rama → entorno: `feature/fix` → solo CI · `develop` → stage · `main` → prod.
  dev es local (docker-compose), sin rama asociada.
