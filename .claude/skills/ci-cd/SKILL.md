---
name: ci-cd
description: Construye y mantiene el pipeline CI/CD de Subastín en GitHub Actions — lint, tests con servicios locales, synth de CDK y gates de deploy por entorno. Usar al crear o modificar workflows de .github/workflows/, al configurar CI para el repo, o cuando se mencione pipeline, GitHub Actions, CI, CD o automatizar checks.
---

# CI/CD (GitHub Actions, adaptado a Subastín)

Pipeline alineado al stack real del repo (Python 3.12 + CDK + Next.js) y al flujo TBD de la
skill `commit`: main siempre verde, ramas cortas validadas por PR.

## Stages del pipeline (en este orden)

| Stage | Comandos | Notas |
|---|---|---|
| lint | `ruff check .` | config en pyproject.toml |
| test backend | `python -m pytest -q` | necesita servicios: dynamodb-local + localstack como `services:` del job (mismas imágenes del docker-compose) |
| synth infra | `cd infra && pip install -r requirements.txt && cdk synth -c stage=stage` | valida la infra sin desplegar; NO necesita credenciales AWS |
| build frontend | `cd frontend && npm ci && npm run build` | cuando el frontend tenga código real |
| deploy stage | `cdk deploy -c stage=stage --require-approval never` | SOLO en push a `develop`, con OIDC + `sts:AssumeRole` a los roles cdk-* (PLAN.md §6.3) — no access keys en secrets |
| deploy prod | `cdk deploy -c stage=prod` | SOLO en push a `main`; gate manual: GitHub Environment `prod` con required reviewers |

CI (lint+test+synth) corre en todo PR y en push a develop/main. CD: develop → stage, main →
prod (modelo de ramas en la skill `commit`), nunca desde ramas feature/fix. Los jobs de deploy
viven en `.github/workflows/deploy.yml` **bloqueados con `if: false` hasta cerrar PLAN.md §6**
(cuenta, bootstrap, OIDC) — las instrucciones de activación están comentadas en el propio YAML.

## Reglas al escribir workflows

- **Seguridad de inputs**: jamás interpolar `${{ github.event.* }}` (títulos, bodies, branch
  names) directo en `run:` — pasar por `env:` con comillas (el hook de la skill
  `security-guidance` también lo vigila).
- Pin de versiones: actions por versión mayor (`actions/checkout@v4`), imágenes de servicio por
  tag, Python por `3.12`.
- Cache de dependencias (`actions/setup-python` con `cache: pip`, `setup-node` con
  `cache: npm`).
- `permissions:` mínimos por workflow (`contents: read` default; `id-token: write` solo en jobs
  de deploy con OIDC).
- Secretos de CI: solo los ARNs/roles de AWS vía OIDC; API keys de IA NUNCA en CI (los tests
  las mockean — skill `testing`).
- Todo cambio de workflow se valida verde en el PR que lo introduce, no después del merge.

## Validación antes de mergear un workflow

1. Los comandos existen y corren local (`ruff`, `pytest`, `cdk synth`).
2. Env vars/secretos requeridos documentados en el propio YAML.
3. Deploy jobs gated por rama protegida + environment.
