"""Settings con pydantic-settings, leido de variables de entorno.

En dev las inyecta `.env` (endpoints locales de docker-compose); en AWS las inyecta CDK
(ver common_env en infra/stacks/subastin_stack.py — mismos nombres: TABLE_*, IMAGES_BUCKET,
AI_JOBS_QUEUE_URL...). Secretos (API keys) NO van aqui: se leen de Secrets Manager en runtime.

Principio del spec (REQUERIMENTS.md §1.1 / RNF-007): limites, TTL y politicas de cierre son
CONFIGURABLES — viven en Settings, jamas hardcodeados en la logica.
"""

# TODO F1: class Settings(BaseSettings) — definir al arrancar la implementacion.
