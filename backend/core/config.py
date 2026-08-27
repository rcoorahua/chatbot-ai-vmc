"""Settings con pydantic-settings, leidos de variables de entorno.

En dev los inyecta `.env` (endpoints locales de docker-compose); en AWS los inyecta CDK
(`common_env` en infra/stacks/subastin_stack.py) con los MISMOS nombres. Los dos secretos que
aparecen aqui (`VMC_IDENTITY_SECRET`, `SESSION_SIGNING_KEY`) solo llegan por variable de entorno
en dev; en stage/prod se leen de Secrets Manager en runtime (PLAN.md §3) — TODO al desplegar.

Principio del spec (REQUERIMENTS.md §1.1 / RNF-007): limites, TTL y politicas son configuracion,
nunca constantes en la logica. Donde la decision de negocio sigue abierta el valor por defecto es
PROVISIONAL y lleva su D-xxx al lado: cambiarlo es editar una variable, no cazar literales.
"""

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_OPTIONAL_TEXT_FIELDS = (
    "dynamodb_endpoint_url",
    "sqs_endpoint_url",
    "s3_endpoint_url",
    "images_bucket",
    "ai_jobs_queue_url",
    "notifications_queue_url",
    "vmc_identity_secret",
    "session_signing_key",
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    stage: str = "dev"
    aws_region: str = "us-east-1"

    # Endpoints locales de docker-compose. None en AWS: boto3 resuelve solo.
    dynamodb_endpoint_url: str | None = None
    sqs_endpoint_url: str | None = None
    s3_endpoint_url: str | None = None

    # Mismos valores por defecto que `nombres_de_tabla()` en scripts/local_setup.py, para que
    # el backend y el script de tablas apunten al mismo sitio sin configurar nada en dev.
    table_conversations: str = "subastin-dev-conversations"
    table_messages: str = "subastin-dev-messages"
    table_tickets: str = "subastin-dev-tickets"
    table_advisors: str = "subastin-dev-advisors"
    table_ai_usage: str = "subastin-dev-ai-usage"
    images_bucket: str | None = None
    ai_jobs_queue_url: str | None = None
    notifications_queue_url: str | None = None

    # ── Identidad del chat (D-001, cerrada 2026-08-27) ──────────────────────────────────────
    # Secreto compartido con VMC: su servidor firma el JWT de identidad del usuario con el y
    # Subastin lo verifica. Es la "key de mi lado" del esquema Intercom (core/auth.py).
    vmc_identity_secret: str | None = None
    # Clave propia con la que Subastin firma el token de sesion del widget. Distinta de la
    # anterior a proposito: rotar la de VMC no invalida las sesiones y viceversa.
    session_signing_key: str | None = None
    session_ttl_hours: int = 12
    # D-018 (sesion anonima): valor PROVISIONAL derivado de la regla "el anonimo no conserva
    # historial" (RF-004). Solo acota cuanto dura el token; los datos los rige D-014.
    anonymous_session_ttl_hours: int = 24

    # ── Limites (RF-014). PROVISIONALES hasta cerrar D-005 ──────────────────────────────────
    # Un mensaje sin tope se convertiria en un item DynamoDB de 400 KB y en un prompt caro.
    max_message_chars: int = 2000
    messages_page_size: int = 50

    # Origenes que pueden llamar a la API desde el navegador. "*" solo en dev: en stage/prod
    # va el dominio de VMC donde vive el widget.
    cors_allowed_origins: str = "*"

    @field_validator(*_OPTIONAL_TEXT_FIELDS, mode="before")
    @classmethod
    def _empty_means_unset(cls, value: object) -> object:
        """`.env.example` deja variables vacias (`SQS_ENDPOINT_URL=`); vacio es "no configurado"."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    """Settings memorizados por proceso (se reusan entre invocaciones de la Lambda tibia)."""
    return Settings()


def reset_settings() -> None:
    """Limpia la memoria. Para tests que cambian variables de entorno."""
    get_settings.cache_clear()
