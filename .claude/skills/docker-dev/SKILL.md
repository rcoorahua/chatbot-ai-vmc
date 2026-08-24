---
name: docker-dev
description: Buenas prácticas de contenedores para Subastín — el docker-compose de dev local y el eventual DockerImageFunction de las Lambdas (TD-005). Usar al modificar docker-compose.yml, crear un Dockerfile, optimizar imágenes o builds, o cuando se mencione Docker, contenedor, imagen, compose o build lento.
---

# Docker Development (adaptado a Subastín)

Docker cumple dos roles aquí: (1) el entorno dev local (`docker-compose.yml`: dynamodb-local +
localstack) y (2) el bundling de Lambdas (`PythonFunction` usa Docker; si las deps superan
~250 MB se pasa a `DockerImageFunction` con Dockerfile propio — TD-005).

## Reglas para docker-compose.yml (dev)

- **Pin de versiones**: tags específicos, no `:latest` (hoy incumplido — corregir al tocar el
  archivo: fijar tags de `amazon/dynamodb-local` y `localstack/localstack`).
- **Healthchecks** por servicio + `depends_on: condition: service_healthy` si un servicio
  depende de otro.
- Exponer solo los puertos necesarios (8001 dynamo, 4566 localstack) y documentar cada uno con
  comentario.
- Variables por `env_file`/`.env`, nunca secretos inline (los de dev son dummies — está bien).
- Cambios al compose se prueban con `docker compose up -d` + un smoke test (listar tablas /
  colas) antes de darlos por buenos.

## Reglas para el futuro Dockerfile de Lambdas (solo si TD-005 se cierra en DockerImageFunction)

- Base: imagen oficial `public.ecr.aws/lambda/python:3.12` (requisito de Lambda), pin de tag.
- Multi-stage: stage de build (pip install con cache mount) → stage runtime solo con
  site-packages y código; sin build tools en la imagen final.
- Orden de capas para cache: `COPY requirements.txt` + install ANTES de `COPY` del código.
- `.dockerignore` obligatorio: `.git`, `.venv`, `node_modules`, `__pycache__`, `.env`, `tests`.
- Jamás secretos en `ENV`/`ARG` (quedan horneados en la capa) — Secrets Manager en runtime.
- Limpiar cache de pip en la misma capa (`--no-cache-dir`).

## Señales proactivas

| Señal | Acción |
|---|---|
| `:latest` en cualquier imagen | Pinnear tag |
| Servicio sin healthcheck en compose | Agregarlo |
| Secreto real en compose o Dockerfile | Bloquear: va a Secrets Manager / .env no versionado |
| Imagen de Lambda > 1 GB | Revisar deps y multi-stage antes de aceptar el cold start |
| `COPY . .` antes de instalar deps | Reordenar: rompe el cache de build |

## Fuera de esta skill

Deploy de la infra → skill `deploy`. Pipelines → skill `ci-cd`.
