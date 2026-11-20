---
paths:
  - "backend/core/**"
  - "backend/api/routers/chat.py"
  - "infra/**"
  - ".env.example"
---

# Secretos e identidad

- Secretos (Gemini/Pinecone/VMC; Slack/HERALD cuando existan) se leen de **Secrets Manager en
  runtime** (implementado 2026-09-02, DETAILS.md §4.2), nunca como variables de entorno del
  stack. En AWS cada Lambda recibe el ARN de SOLO lo que consume (`IDENTITY_SECRET_ARN` en
  `api`, `AI_SECRET_ARN` en `worker-ai`; `worker-notify` no lee ninguno) y
  `core/config.get_settings()` los resuelve una vez por proceso, ANTES de construir `Settings`,
  volcandolos a las mismas variables de entorno que ya leia en dev (`_resolve_secrets_into_env`).
  CDK solo crea el secreto vacio (`GenerateSecretString: {}`) y el permiso de lectura — el valor
  real (`VMC_IDENTITY_SECRET` es compartido con VMC; las API keys son de terceros) se carga a
  mano con `aws secretsmanager put-secret-value` despues del primer deploy, nunca en el codigo
  ni en la plantilla de CloudFormation. `anthropic_api_key` sigue sin secreto: nada lo consume
  todavia (DETAILS.md §4.23), agregarlo cuando exista el consumidor real.
- `POST /chat/sessions` valida que exista `SESSION_SIGNING_KEY` ANTES de abrir la conversacion
  (`auth.ensure_session_signing_configured()`, DETAILS.md §4.2): antes, un anonimo sin la clave
  dejaba una fila huerfana en cada intento porque el 503 llegaba recien al firmar el token.
- Dos secretos de identidad y no uno: `VMC_IDENTITY_SECRET` (lo comparte VMC, firma el JWT de
  identidad) y `SESSION_SIGNING_KEY` (propio, firma el token de sesión). Unificarlos permitiría
  presentar un token de sesión como identidad de VMC — `tests/test_core_auth.py` lo cubre.
