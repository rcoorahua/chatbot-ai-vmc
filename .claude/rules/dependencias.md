---
paths:
  - "pyproject.toml"
  - "requirements-lock.txt"
  - "backend/requirements-*.txt"
  - "infra/requirements.txt"
---

# Dependencias

- Deps: `backend/requirements-{api,worker-ai,worker-notify}.txt` es lo que CDK bundlea por
  función (separadas para no cargar cada Lambda con lo que no usa — ver infra/stacks/
  subastin_stack.py); `pyproject.toml` es el entorno local de dev — mantener los cuatro en sync
  con lo que realmente se importa al agregar una dependencia. `requirements-lock.txt` (raíz)
  fija las versiones exactas resueltas para `pyproject.toml[dev]`; lo instala el job `test` de
  CI (DETAILS.md §4 Paso 4) y se regenera con el comando en su propio encabezado tras tocar
  `dependencies`/`dev` — **no** cubre los `backend/requirements-*.txt` (lo que va a Lambda) ni
  `infra/requirements.txt` (pineados por versión exacta en el propio archivo, sin lock aparte).
