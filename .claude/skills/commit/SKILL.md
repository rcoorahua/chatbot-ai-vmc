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
7. **PR a develop** (nunca push directo a develop/main). Título = el commit principal; cuerpo =
   RF/AC cubiertos + qué se probó + decisiones tomadas y por qué.
8. **Esperar el CI** y no darlo por bueno sin verlo: `lint`, `test` y `synth` en verde. Los
   `deploy-*` en `skipping` es lo esperado mientras no haya cuenta AWS.
9. **Merge a develop** con squash; borrar la rama.
10. **Release**: PR `develop → main`, título `release: <resumen>`, esperar CI y **mergear con
    squash** (sin borrar `develop`). El deploy a prod tiene gate manual (skill `deploy`).

**Squash SIEMPRE, también en el release**, y el flujo va en UNA dirección: `develop → main`.
Nunca un PR `main → develop`.

`develop` y `main` SIEMPRE figuran con "N adelante / M atrás" — con squash y con merge normal.
Es inevitable: ambos reescriben o agregan commits en el destino. **Ese número no es un problema
y no se arregla.** Lo único que importa es que el contenido coincida:

```powershell
git diff --stat origin/main origin/develop   # vacío = ramas equivalentes, todo bien
```

Si sale vacío, no hay nada que hacer. Un PR `main → develop` para "alinear" invierte el flujo,
mete un merge commit en el trunk y no cambia el contenido: es ruido, no una corrección.

### Comandos de PR (GitHub CLI)

`gh` está autenticado; una terminal abierta antes de instalarlo no lo ve en el PATH.

```powershell
$gh = "$env:ProgramFiles\GitHub CLI\gh.exe"
& $gh pr create --base develop --head <rama> --title "<titulo>" --body-file <archivo.md>
& $gh pr checks <n> --watch --interval 15     # espera a que terminen los checks
& $gh pr merge <n> --squash --delete-branch   # a develop
& $gh pr merge <n> --squash                   # release a main: sin borrar develop
```

Trampas verificadas: el cuerpo va siempre en archivo (`--body-file`) porque los here-strings con
tablas hacen saltar filtros del shell; y `gh pr merge` escribe a stderr al terminar, así que el
resultado se confirma con `gh pr view <n> --json state,mergedAt` antes de reportarlo.

## Conventional Commits

Formato `<type>[scope]: <descripción>` + cuerpo y footers opcionales.

**Types**: `feat` · `fix` · `chore` · `docs` · `style` · `refactor` · `test`.
**Scope** = módulo: `conversations`, `tickets`, `advisors`, `agent`, `catalog`, `notifications`,
`images`, `api`, `workers`, `core`, `infra`, `frontend`, `skills`, `ci`.

- Descripción en imperativo, minúscula inicial, sin punto final, ≤ 72 caracteres.
- Trazabilidad spec-driven en el cuerpo: `Implementa RF-xxx / AC-xxx` · `Cierra D-xxx`.
  Ejemplo: `feat(conversations): mensaje fijo de espera una sola vez por periodo` +
  cuerpo `Implementa RF-027 / AC-004.`
- Breaking change: `!` tras type/scope + footer `BREAKING CHANGE: <detalle>`.
- Footer de coautoría de Claude según el harness (Co-Authored-By).

## Protecciones activas

- **En GitHub** (repo público, lo que habilita estas reglas en plan Free): `main` y `develop`
  exigen PR y los tres checks en verde, con la rama al día; force push y borrado bloqueados. En
  `main` aplica también a administradores — nadie la salta. En `develop` no, para un hotfix.
- **Environment `prod`**: aprobación manual antes de cualquier despliegue a producción.
- **Hook local `pre-push`** (`.githooks/pre-push`, activar con
  `git config core.hooksPath .githooks`): bloquea el push directo antes de llegar al servidor.
  Emergencias: `ALLOW_DIRECT_PUSH=1 git push ...`.

Un PR no se mergea hasta que el CI pase. Si un check falla, se arregla en la misma rama.

## Reglas de esta base

- Commitear/pushear solo cuando el usuario lo pida; al hacerlo, este protocolo completo.
- Jamás commitear `.env`, tokens, backups, `.venv/`, `node_modules/`, `__pycache__/`.
- Tokens de GitHub: nunca en el chat, en la URL del remoto ni en archivos; el usuario los usa
  desde su credential manager. Si un push falla por auth, dar el comando para que lo corra él.
- Ramas de más de 3 días: avisar y proponer partirlas; nada de ramas eternas.
- Mapeo rama → entorno: `feature/fix` → solo CI · `develop` → stage · `main` → prod.
  dev es local (docker-compose), sin rama asociada.
