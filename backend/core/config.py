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
    table_rate_limits: str = "subastin-dev-rate-limits"
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

    # ── Asesores (RF-006, T1) ───────────────────────────────────────────────────────────────
    # En AWS el JWT de Cognito lo valida el authorizer del API Gateway y la Lambda recibe los
    # claims en el evento; el backend nunca ve el token. En local no hay API Gateway, asi que
    # `ADVISOR_DEV_AUTH=1` activa un middleware que imita al authorizer: verifica un JWT HS256
    # firmado con `ADVISOR_DEV_JWT_SECRET` y deja los claims en el mismo sitio del evento
    # (backend/api/dev_auth.py). Se ignora dentro de una Lambda aunque este activado.
    advisor_dev_auth: bool = False
    advisor_dev_jwt_secret: str | None = None
    # Cuantos mensajes ve el asesor al abrir un hilo (RF-012/RF-033): los ultimos N, con
    # paginacion hacia atras para el historial completo.
    advisor_thread_page_size: int = 20
    inbox_page_size: int = 50

    # ── Proveedores de IA (TD-008) ───────────────────────────────────────────────────────────
    # SOLO en dev llegan por `.env`; en stage/prod se resuelven desde Secrets Manager antes de
    # construir Settings. `core/llm.py` las lee de aqui (no de `os.environ`): pydantic carga
    # `.env` en Settings pero no lo exporta al proceso, asi que leer el entorno directo dejaba
    # la key de `.env` invisible y el bot caia al fallback sin avisar.
    gemini_api_key: str | None = None
    anthropic_api_key: str | None = None

    # ── RAG en Pinecone (RF-017/018/019) ────────────────────────────────────────────────────
    # Mismos nombres de variable que usaba el proyecto de referencia, para que una credencial
    # ya existente sirva sin renombrar nada.
    pinecone_api_key: str | None = None
    pinecone_index_name: str = "subastin-rag"
    # Un namespace por fuente de conocimiento: hoy solo el Centro de Ayuda. Separarlos permite
    # re-subir una fuente entera sin tocar las demas.
    pinecone_namespace: str = "helpcenter"
    # Cuantos fragmentos se le pasan al redactor. Mas de 5 encarece el prompt y mete ruido
    # (regla de la skill rag-architect); menos de 3 se queda corto en preguntas compuestas.
    rag_top_k: int = 4
    # Umbral de RF-018: por debajo de esto se considera que NO hay evidencia y el caso deriva,
    # en vez de redactar con fragmentos que no vienen al caso.
    # OJO: hay que calibrarlo con datos reales. `python -m scripts.helpcenter_upload --verify`
    # imprime los scores de una consulta de prueba; el valor por defecto asume el rango tipico
    # de multilingual-e5-large (similitudes altas y comprimidas), no esta medido todavia.
    rag_min_score: float = 0.84

    # ── Pipeline IA (D-006 y D-020 cerradas 2026-08-28) ─────────────────────────────────────
    # D-020: cada mensaje encola su job con este retraso (DelaySeconds de SQS). Al procesarlo,
    # si el usuario ya escribio algo mas nuevo, el job se salta y responde el job del ultimo
    # mensaje con el bloque completo: una llamada IA por rafaga, sin estado extra. 0 lo apaga.
    ai_debounce_seconds: int = 6
    # D-006: un mensaje identico repetido dentro de esta ventana no vuelve a pagar llamada IA;
    # recibe una respuesta fija (una vez) que ofrece un asesor.
    trivial_repeat_window_minutes: int = 10
    # Tope de salida del redactor (RF-020). Caben 3-4 frases con margen; la brevedad la pide el
    # prompt, el tope la garantiza. Configurable por RNF-007 (antes era literal en writer.py).
    ai_answer_max_tokens: int = 600

    # ── Ventana de contexto para la IA (RF-013, D-004 cerrada 2026-08-28) ───────────────────
    # La memoria del bot son los ultimos N mensajes DE LA ULTIMA HORA. No hay resumen: la
    # conversacion del autenticado es permanente (D-003), asi que sin corte temporal el bot
    # arrastraria para siempre un hilo de hace semanas — caro y confuso. Si el usuario vuelve
    # despues de la ventana, su mensaje se atiende solo, que es lo que espera quien retoma.
    ai_context_messages: int = 20
    ai_context_window_minutes: int = 60

    # ── Limites contra abuso (RF-014 / RNF-007, D-005 cerrada 2026-08-28) ───────────────────
    # Un mensaje sin tope se convertiria en un item DynamoDB de 400 KB y en un prompt caro.
    max_message_chars: int = 500
    messages_page_size: int = 50
    # Rate limit por conversacion (que con D-002 es por usuario): ritmo humano incluso
    # escribiendo rapido y en frases partidas. Pasarse devuelve 429, no pierde el mensaje.
    max_messages_per_minute: int = 10
    # SIN tope acumulativo de mensajes por conversacion, a proposito: con D-003 la conversacion
    # del autenticado no se cierra nunca, asi que un tope duro la dejaria inservible de por vida
    # y habria que intervenir a mano. El crecimiento lo controlan el rate limit y la retencion
    # (D-014), no un contador que solo sube.

    # ── Tope de ejecuciones de IA por actor (T-09 / D-027, revisada 2026-09-01) ─────────────
    # Complementa al rate limit de arriba: aquel es por minuto y por conversacion; esto frena
    # el costo ACUMULADO de un mismo actor. Cuenta mensajes que llamaron a un modelo (los
    # triviales, guardrails, reglas y ofrecer botones de flujo no gastan porque no cuestan).
    # 0 = sin tope, y ASI QUEDA EN DEV (decision de Aaron 2026-09-01: apagado por ahora).
    # Valores decididos para prod: anonimo 10/hora y 20/dia (por sesion Y por hash de IP, se
    # agota la primera); autenticado el doble (20/hora y 40/dia) por user_id. Al agotarse:
    # respuesta fija que orienta a crear cuenta (anonimo) o pedir asesor (autenticado) — pedir
    # asesor sale por reglas, sin modelo, asi que funciona incluso sin cuota.
    ai_quota_anon_per_hour: int = 0
    ai_quota_anon_per_day: int = 0
    ai_quota_auth_per_hour: int = 0
    ai_quota_auth_per_day: int = 0
    # Sal del HMAC con el que se hashea la IP (dato personal, jamas en claro). Vacio = se usa
    # session_signing_key; rotarla reinicia contadores, aceptable con ventanas de horas.
    ip_hash_secret: str | None = None

    # ── Casos y handoff con formulario (D-029, cerrada 2026-09-02) ──────────────────────────
    # Autenticado: un hilo permanente con el bot y hasta N casos abiertos (PENDING_ADVISOR o
    # IN_ATTENTION) a la vez. Al llegar al tope, el formulario responde 409 y el widget invita
    # a seguir en un caso abierto. 0 = sin tope.
    max_open_cases_per_user: int = 5
    # Anonimo: cuantos handoffs por dia acepta una misma IP (hasheada). Frena al que abre
    # pestañas para inundar la bandeja con correos falsos. 0 = sin tope, y asi queda en dev
    # (misma politica que AI_QUOTA_*); en stage/prod se enciende por variable de entorno.
    anon_handoffs_per_ip_per_day: int = 0
    # La conversacion anonima (y sus mensajes) caduca sola por TTL de DynamoDB: sin cuenta no
    # hay forma de volver a ella, asi que conservarla mas alla de un margen operativo solo
    # acumula chats muertos. 0 = sin TTL. El valor definitivo de retencion lo fija D-014.
    anonymous_conversation_ttl_days: int = 30

    # ── Imagenes (RF-040..042, valores de D-005; se aplican en F6) ──────────────────────────
    # Mismo criterio que arriba: todos los topes se renuevan (por imagen, por mensaje, por
    # hora). Ninguno es acumulativo, asi que el usuario nunca se queda sin poder enviar fotos.
    max_image_bytes: int = 5 * 1024 * 1024
    max_images_per_message: int = 3
    max_images_per_hour: int = 20
    allowed_image_types: str = "image/jpeg,image/png,image/webp"

    # Origenes que pueden llamar a la API desde el navegador. "*" solo en dev: en stage/prod
    # va el dominio de VMC donde vive el widget.
    cors_allowed_origins: str = "*"

    # ── Observabilidad (RNF-006; politica de Aaron 2026-08-28) ──────────────────────────────
    # dev y stage detallados, prod sobrio. `None` = "decidir por stage" (ver las propiedades
    # `effective_*`): asi un `.env` copiado de la plantilla no fija nada y prod no hereda el
    # nivel de dev por accidente. En AWS los inyecta el stack por stage.
    log_level: str | None = None  # DEBUG | INFO | WARNING | ERROR
    log_content: bool | None = None  # vista previa del texto de los mensajes en los logs
    log_format: str | None = None  # json | text
    # Rutas /dev/* (consola de widget/test.html). Solo metricas de la conversacion propia.
    dev_observability: bool | None = None

    @property
    def effective_log_level(self) -> str:
        if self.log_level:
            return self.log_level.upper()
        return "INFO" if self.stage == "prod" else "DEBUG"

    @property
    def effective_log_content(self) -> bool:
        return self.log_content if self.log_content is not None else self.stage != "prod"

    @property
    def effective_log_format(self) -> str:
        if self.log_format:
            return self.log_format.lower()
        import os

        return "json" if os.environ.get("AWS_LAMBDA_FUNCTION_NAME") else "text"

    @property
    def dev_observability_enabled(self) -> bool:
        if self.dev_observability is not None:
            return self.dev_observability
        return self.stage != "prod"

    @field_validator("*", mode="before")
    @classmethod
    def _empty_keeps_default(cls, value: object, info) -> object:
        """Una variable vacia en `.env` cae al default del campo, no a cadena vacia.

        `.env.example` deja casi todo vacio (`AWS_REGION=`, `TABLE_MESSAGES=`, …) y hay `.env`
        reales copiados tal cual. Sin esto, `aws_region=""` hace que boto3 arme endpoints
        invalidos (`dynamodb..amazonaws.com`) y un nombre de tabla vacio rompe cada consulta:
        errores que aparecen lejos de la causa, al usar el client y no al leer la configuracion.

        Los opcionales (`SQS_ENDPOINT_URL`, secretos, …) tienen default None, asi que quedan en
        None: "vacio" y "no configurado" son lo mismo. Los flags booleanos caen a su default en
        vez de romper con un error de parseo. Un campo sin default se deja como esta y pydantic
        reporta que falta, que es lo correcto.
        """
        if not isinstance(value, str) or value.strip():
            return value
        field = cls.model_fields.get(info.field_name)
        return field.default if field is not None and not field.is_required() else value

    @property
    def image_types(self) -> list[str]:
        return [item.strip() for item in self.allowed_image_types.split(",") if item.strip()]

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
