---
name: deploy
description: Runbook de deploy de Subastín con CDK v2 en Python para stage y prod, con precondiciones verificables y gate manual en prod. Usar cuando el usuario pida desplegar, hacer release, o mencione cdk deploy, synth, diff, watch, destroy o bootstrap. dev NO se despliega (es docker-compose local).
---

# Deploy — CDK v2 Python (stage/prod)

## Precondiciones (verificar EN ORDEN; abortar y avisar si alguna falla)

1. **Suite de tests en verde** (skill `testing`) — nunca desplegar con tests rojos.
2. **Docker corriendo** — cada Lambda bundlea su propio `backend/requirements-{api,worker-ai,
   worker-notify}.txt` dentro de Docker (`Code.from_asset(bundling=...)`, no `PythonFunction`).
3. **Cuenta lista** (PLAN.md §6): bootstrap hecho (`cdk bootstrap aws://<account>/<region>`),
   credenciales con `sts:AssumeRole` sobre `arn:aws:iam::*:role/cdk-*`, y `account`/`region`
   completados en `infra/config.py`. Si falta algo → checklist de PLAN.md §6 con el equipo AWS;
   no inventar valores.
4. **Primer deploy real además bloqueado por**: ajustes 1–5 del modelo de datos (PLAN.md §4)
   cerrados — los GSI no se backfillean solos.
5. `cdk synth -c stage=<stage>` limpio (`cd infra`, `pip install -r requirements.txt` la
   primera vez).

## Comandos

```bash
cdk synth  -c stage=stage     # validar template
cdk diff   -c stage=stage     # ver qué cambia
cdk deploy -c stage=stage
cdk watch  -c stage=stage     # iteración: hotswap de código (~3s); tocar infra = deploy completo
cdk deploy -c stage=prod      # ver regla de prod abajo
```

## Reglas

- **prod SIEMPRE requiere confirmación explícita del usuario en esa conversación** — nunca como
  efecto colateral. Antes: `cdk diff -c stage=prod` y mostrar el resumen de cambios.
- **destroy** solo bajo pedido explícito; en prod tablas/bucket tienen `RETAIN` (los datos
  sobreviven al stack — avisarlo).
- Cambiar un GSI o clave de tabla con datos en stage/prod = migración manual → avisar y planear
  antes de tocar.
- **Tras cada deploy**: probar `GET /health` con el `ApiUrl` del output; verificar DLQs vacías
  y sin alarmas.
- Secretos solo en Secrets Manager; jamás en env vars en claro, código u outputs.
- dev nunca se despliega: es `docker compose up -d` local (decisión T5).
