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
9. **Merge a develop**: squash si la rama trae commits WIP, merge normal si cada commit es
   limpio; borrar la rama.
10. **PR de develop → main** con título `release: <resumen>`, esperar CI y mergear (merge normal,
    sin borrar `develop`). El deploy a prod tiene gate manual (skill `deploy`).
11. **Sincronizar develop con main**: tras el release, `develop` queda detrás por los merge
    commits que crea GitHub. Se arregla con un PR `main → develop` (`chore: sincronizar...`),
    NUNCA con push directo — el hook `pre-push` lo bloquea y saltarlo con `ALLOW_DIRECT_PUSH`
    no es la vía.

### Comandos de PR (GitHub CLI)

`gh` está instalado en `C:\Program Files\GitHub CLI\gh.exe` y autenticado. Una terminal abierta
antes de instalarlo no lo ve en el PATH: usar la ruta completa o abrir una nueva.

```powershell
$gh = "$env:ProgramFiles\GitHub CLI\gh.exe"
& $gh pr create --base develop --head <rama> --title "<titulo>" --body-file <archivo.md>
& $gh pr checks <n> --watch --interval 15     # espera a que terminen los checks
& $gh pr merge <n> --squash --delete-branch   # a develop
& $gh pr merge <n> --merge                    # release a main: sin borrar la rama
```

El cuerpo va **siempre en archivo** (`--body-file`), nunca inline: los here-strings con tablas
markdown y rutas hacen saltar filtros del shell. Escribirlo con la herramienta Write al
scratchpad y pasar la ruta.

`gh pr merge` escribe a stderr al hacer el `git fetch` posterior; PowerShell lo muestra como
error aunque haya funcionado. Confirmar siempre con
`gh pr view <n> --json number,state,mergedAt` antes de reportar el resultado.

Sin `gh` disponible: abrir
`https://github.com/rcoorahua/chatbot-ai-vmc/compare/develop...<rama>?expand=1` y que el usuario
cree el PR a mano.

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

## Protecciones activas

- **En GitHub** (repo público, lo que habilita estas reglas en plan Free): `main` y `develop`
  exigen pull request y los checks `lint`, `test`, `synth` en verde, con la rama al día; force
  push y borrado bloqueados. En `main` la regla aplica también a administradores — **nadie
  puede saltarla, ni con permisos de admin**. En `develop` no, para permitir un hotfix.
- **Environment `prod`**: aprobación manual antes de cualquier despliegue a producción.
- **Hook local `pre-push`** (`.githooks/pre-push`, activar con
  `git config core.hooksPath .githooks`): bloquea el push directo antes de llegar al servidor.
  Emergencias: `ALLOW_DIRECT_PUSH=1 git push ...`.

Consecuencia práctica: un PR **no se puede mergear** hasta que el CI pase. Si un check falla,
se arregla en la misma rama y se vuelve a pushear; no hay atajo.

## Reglas de esta base

- Commitear/pushear solo cuando el usuario lo pida; al hacerlo, este protocolo completo.
- Jamás commitear `.env`, tokens, backups, `.venv/`, `node_modules/`, `__pycache__/`.
- Tokens de GitHub: nunca en el chat, en la URL del remoto ni en archivos; el usuario los usa
  desde su credential manager. Si un push falla por auth, dar el comando para que lo corra él.
- Ramas de más de 3 días: avisar y proponer partirlas; nada de ramas eternas.
- Mapeo rama → entorno: `feature/fix` → solo CI · `develop` → stage · `main` → prod.
  dev es local (docker-compose), sin rama asociada.
