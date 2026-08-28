"""Stack unico de Subastin, parametrizado por stage.

ESQUELETO — NO DESPLEGADO NUNCA. Expresa que recursos existen y como se conectan (PLAN.md §2-§3).
Antes de el primer `cdk deploy` real: cerrar los ajustes 1-5 del modelo de datos (PLAN.md §4)
porque los GSI no se pueden backfillear solos, y completar account/region en config.py.
"""

import aws_cdk as cdk
from aws_cdk import (
    Duration,
    RemovalPolicy,
    Stack,
)
from aws_cdk import (
    aws_apigatewayv2 as apigwv2,
)
from aws_cdk import (
    aws_apigatewayv2_authorizers as authorizers,
)
from aws_cdk import (
    aws_apigatewayv2_integrations as integrations,
)
from aws_cdk import (
    aws_cognito as cognito,
)
from aws_cdk import (
    aws_dynamodb as dynamodb,
)
from aws_cdk import (
    aws_lambda as lambda_,
)
from aws_cdk import (
    aws_lambda_event_sources as event_sources,
)
from aws_cdk import (
    aws_s3 as s3,
)
from aws_cdk import (
    aws_sqs as sqs,
)
from aws_cdk.aws_lambda_python_alpha import PythonFunction  # bundling requiere Docker corriendo
from config import StageConfig
from constructs import Construct


class SubastinStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *, cfg: StageConfig, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        removal = RemovalPolicy.RETAIN if cfg.retain_data else RemovalPolicy.DESTROY
        prefix = f"subastin-{cfg.stage}"

        # ────────────────────────── DynamoDB — 5 tablas (PLAN.md §4) ──────────────────────────
        # Todas PAY_PER_REQUEST. Los GSI de abajo son los acordados; los ajustes 1-5 de la
        # revision (unread_count, wait_message_sent, expires_at en Messages, item marcador de
        # idempotencia, GSI2 sparse) son atributos/patrones de item — no cambian esta definicion,
        # salvo que se adopte el GSI sparse (ajuste 5), que SI cambia GSI2 antes del primer deploy.

        conversations = dynamodb.Table(
            self,
            "Conversations",
            table_name=f"{prefix}-conversations",
            partition_key=dynamodb.Attribute(
                name="conversation_id", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            time_to_live_attribute="expires_at",  # valor concreto de retencion → D-014
            removal_policy=removal,
        )
        conversations.add_global_secondary_index(
            index_name="gsi1_user",
            partition_key=dynamodb.Attribute(name="user_id", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="updated_at", type=dynamodb.AttributeType.STRING),
        )
        conversations.add_global_secondary_index(
            # ajuste 5 pendiente: ¿PK sparse `inbox_status` en vez de `status`?
            index_name="gsi2_inbox",
            partition_key=dynamodb.Attribute(name="status", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="last_message_at", type=dynamodb.AttributeType.STRING),
        )
        conversations.add_global_secondary_index(
            index_name="gsi3_advisor",
            partition_key=dynamodb.Attribute(
                name="assigned_advisor_id", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(name="updated_at", type=dynamodb.AttributeType.STRING),
        )

        messages = dynamodb.Table(
            self,
            "Messages",
            table_name=f"{prefix}-messages",
            partition_key=dynamodb.Attribute(
                name="conversation_id", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="message_key", type=dynamodb.AttributeType.STRING
            ),  # created_at#message_id
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            time_to_live_attribute="expires_at",  # ajuste 3 de la revision; valor → D-014
            removal_policy=removal,
        )

        tickets = dynamodb.Table(
            self,
            "Tickets",
            table_name=f"{prefix}-tickets",
            partition_key=dynamodb.Attribute(name="ticket_id", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=removal,
        )
        tickets.add_global_secondary_index(
            index_name="gsi1_conversation",
            partition_key=dynamodb.Attribute(
                name="conversation_id", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(name="created_at", type=dynamodb.AttributeType.STRING),
        )
        tickets.add_global_secondary_index(
            index_name="gsi2_advisor",
            partition_key=dynamodb.Attribute(
                name="assigned_advisor_id", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(name="updated_at", type=dynamodb.AttributeType.STRING),
        )
        tickets.add_global_secondary_index(
            index_name="gsi3_status",
            partition_key=dynamodb.Attribute(name="status", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="created_at", type=dynamodb.AttributeType.STRING),
        )

        advisors = dynamodb.Table(
            self,
            "Advisors",
            table_name=f"{prefix}-advisors",
            partition_key=dynamodb.Attribute(name="advisor_id", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=removal,
        )
        advisors.add_global_secondary_index(
            index_name="gsi_cognito",
            partition_key=dynamodb.Attribute(
                name="cognito_sub", type=dynamodb.AttributeType.STRING
            ),
        )

        ai_usage = dynamodb.Table(
            self,
            "AIUsage",
            table_name=f"{prefix}-ai-usage",
            partition_key=dynamodb.Attribute(
                name="conversation_id", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="execution_key", type=dynamodb.AttributeType.STRING
            ),  # created_at#execution_id
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            # sin TTL a proposito: los datos de costo se conservan (confirmar en D-014)
            removal_policy=removal,
        )
        ai_usage.add_global_secondary_index(
            index_name="gsi_billing",
            partition_key=dynamodb.Attribute(
                name="billing_month", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(name="created_at", type=dynamodb.AttributeType.STRING),
        )

        # ─────────────────────────────── S3 — imagenes (RF-042) ───────────────────────────────
        images_bucket = s3.Bucket(
            self,
            "ImagesBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=removal,
            # TODO D-014: lifecycle rule de retencion (¿6 meses?) — no configurar hasta cerrarla.
            # TODO D-005: limites de tamaño se validan en la API al firmar el presigned URL.
        )

        # ─────────────────────────── Cognito — asesores (RF-006/007) ───────────────────────────
        user_pool = cognito.UserPool(
            self,
            "AdvisorsPool",
            user_pool_name=f"{prefix}-advisors",
            self_sign_up_enabled=False,  # solo invitacion por correo (RF-006)
            sign_in_aliases=cognito.SignInAliases(email=True),
            removal_policy=removal,
        )
        user_pool_client = user_pool.add_client("AdvisorsWebClient")

        # ──────────────────────────────── SQS — colas + DLQs (T3) ───────────────────────────────
        ai_jobs_dlq = sqs.Queue(self, "AiJobsDlq", queue_name=f"{prefix}-ai-jobs-dlq")
        ai_jobs = sqs.Queue(
            self,
            "AiJobs",
            queue_name=f"{prefix}-ai-jobs",
            # Regla cerrada: visibility >= 6x timeout del worker (si no, SQS re-entrega en proceso).
            visibility_timeout=Duration.seconds(6 * cfg.worker_ai_timeout_s),
            dead_letter_queue=sqs.DeadLetterQueue(max_receive_count=3, queue=ai_jobs_dlq),
            # D-020: el debounce puede usar DelaySeconds por mensaje — decidir antes de F2.
        )
        notifications_dlq = sqs.Queue(
            self, "NotificationsDlq", queue_name=f"{prefix}-notifications-dlq"
        )
        notifications = sqs.Queue(
            self,
            "Notifications",
            queue_name=f"{prefix}-notifications",
            visibility_timeout=Duration.seconds(6 * 30),
            dead_letter_queue=sqs.DeadLetterQueue(max_receive_count=3, queue=notifications_dlq),
        )

        # ──────────────────────────────────── Lambdas (T2/T3) ───────────────────────────────────
        # PythonFunction bundlea backend/requirements.txt dentro de Docker (TD-005 si crece >250MB).
        common_env = {
            "STAGE": cfg.stage,
            # Observabilidad por stage (RNF-006): el formato es JSON dentro de Lambda por
            # defecto (core/observability.py lo detecta), asi que aqui solo va nivel y politica.
            "LOG_LEVEL": cfg.log_level,
            "LOG_CONTENT": "1" if cfg.log_content else "0",
            "DEV_OBSERVABILITY": "1" if cfg.dev_observability else "0",
            "TABLE_CONVERSATIONS": conversations.table_name,
            "TABLE_MESSAGES": messages.table_name,
            "TABLE_TICKETS": tickets.table_name,
            "TABLE_ADVISORS": advisors.table_name,
            "TABLE_AI_USAGE": ai_usage.table_name,
            "IMAGES_BUCKET": images_bucket.bucket_name,
            "CORS_ALLOWED_ORIGINS": cfg.cors_allowed_origins,
            # Guardrails y ventana de contexto (RNF-007: configuracion, no constantes). Van
            # explicitos aunque coincidan con los defaults de core/config.py para poder ajustarlos
            # en la consola de Lambda durante un incidente, sin desplegar codigo.
            # Valores de D-004 y D-005, cerradas el 2026-08-28.
            "AI_DEBOUNCE_SECONDS": "6",
            "TRIVIAL_REPEAT_WINDOW_MINUTES": "10",
            "AI_ANSWER_MAX_TOKENS": "600",
            "AI_CONTEXT_MESSAGES": "20",
            "AI_CONTEXT_WINDOW_MINUTES": "60",
            "MAX_MESSAGE_CHARS": "2000",
            "MAX_MESSAGES_PER_MINUTE": "10",
            "MAX_IMAGE_BYTES": str(5 * 1024 * 1024),
            "MAX_IMAGES_PER_MESSAGE": "3",
            "MAX_IMAGES_PER_HOUR": "20",
            "ALLOWED_IMAGE_TYPES": "image/jpeg,image/png,image/webp",
            # Secretos (Anthropic/Gemini/Pinecone/Slack/HERALD/VMC): leer de Secrets Manager por
            # ARN en runtime, NUNCA como variables de entorno en claro (PLAN.md §3). Incluye los
            # dos de identidad del chat (D-001): VMC_IDENTITY_SECRET (compartido con VMC) y
            # SESSION_SIGNING_KEY (propio). Hoy backend/core/config.py los lee del entorno; al
            # desplegar hay que resolverlos desde el secreto antes de construir Settings.
        }

        api_fn = PythonFunction(
            self,
            "ApiFn",
            entry="../backend",
            index="api/main.py",
            handler="handler",
            runtime=lambda_.Runtime.PYTHON_3_12,
            memory_size=cfg.api_memory_mb,
            timeout=Duration.seconds(15),  # la API no llama a la IA (T8)
            environment={**common_env, "AI_JOBS_QUEUE_URL": ai_jobs.queue_url},
        )

        worker_ai_fn = PythonFunction(
            self,
            "WorkerAiFn",
            entry="../backend",
            index="workers/ai_worker.py",
            handler="handler",
            runtime=lambda_.Runtime.PYTHON_3_12,
            memory_size=1024,
            timeout=Duration.seconds(cfg.worker_ai_timeout_s),
            environment={**common_env, "NOTIFICATIONS_QUEUE_URL": notifications.queue_url},
        )
        worker_ai_fn.add_event_source(
            event_sources.SqsEventSource(ai_jobs, batch_size=5, report_batch_item_failures=True)
        )

        worker_notify_fn = PythonFunction(
            self,
            "WorkerNotifyFn",
            entry="../backend",
            index="workers/notify_worker.py",
            handler="handler",
            runtime=lambda_.Runtime.PYTHON_3_12,
            timeout=Duration.seconds(30),
        )
        worker_notify_fn.add_event_source(
            event_sources.SqsEventSource(
                notifications, batch_size=5, report_batch_item_failures=True
            )
        )

        # TODO D-003/D-018: `worker-maintenance` (EventBridge Schedule) SOLO si el autocierre por
        # inactividad o la expiracion de sesion anonima lo exigen. No crear hasta cerrarlas.

        # Permisos via grants (T4: cero JSON de IAM a mano)
        for table in (conversations, messages, tickets, advisors, ai_usage):
            table.grant_read_write_data(api_fn)
            table.grant_read_write_data(worker_ai_fn)
        images_bucket.grant_read_write(api_fn)  # presigned URLs
        images_bucket.grant_read(worker_ai_fn)  # interpretacion de imagenes (D-015)
        ai_jobs.grant_send_messages(api_fn)
        notifications.grant_send_messages(worker_ai_fn)
        # TODO: grants de Secrets Manager cuando existan los secretos (PLAN.md §6.5).

        # ──────────────── API Gateway HTTP API — mapa de rutas (T1, PLAN.md §3) ────────────────
        http_api = apigwv2.HttpApi(
            self,
            "HttpApi",
            api_name=f"{prefix}-api",
            # El preflight CORS lo responde FastAPI (CORSMiddleware con CORS_ALLOWED_ORIGINS):
            # la ruta $default tambien recibe OPTIONS, asi que no hace falta cors_preflight aqui.
        )
        api_integration = integrations.HttpLambdaIntegration("ApiIntegration", api_fn)
        cognito_authorizer = authorizers.HttpJwtAuthorizer(
            "CognitoAuthorizer",
            f"https://cognito-idp.{cfg.region}.amazonaws.com/{user_pool.user_pool_id}",
            jwt_audience=[user_pool_client.user_pool_client_id],
        )

        # /advisor/* y /dashboard/* exigen JWT de Cognito EN EL GATEWAY:
        # sin token valido, la Lambda ni siquiera se invoca.
        http_api.add_routes(
            path="/advisor/{proxy+}", integration=api_integration, authorizer=cognito_authorizer
        )
        http_api.add_routes(
            path="/dashboard/{proxy+}", integration=api_integration, authorizer=cognito_authorizer
        )
        # Todo lo demas (chat publico, /health) cae en $default → misma Lambda; la identidad del
        # chat (VMC / sesion anonima) se valida DENTRO de FastAPI segun D-001/D-018.
        apigwv2.HttpRoute(
            self,
            "DefaultRoute",
            http_api=http_api,
            route_key=apigwv2.HttpRouteKey.DEFAULT,
            integration=api_integration,
        )

        # TODO RNF-006: alarmas CloudWatch (DLQ > 0, errores de workers, 5xx/latencia del API).

        cdk.CfnOutput(self, "ApiUrl", value=http_api.api_endpoint)  # lo consume el frontend
        cdk.CfnOutput(self, "UserPoolId", value=user_pool.user_pool_id)
        cdk.CfnOutput(self, "UserPoolClientId", value=user_pool_client.user_pool_client_id)
