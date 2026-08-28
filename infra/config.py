"""Configuracion por stage (stage/prod). Todo lo que difiere entre entornos vive aqui.

PENDIENTE (bloqueado por PLAN.md §6): account IDs y region los define el equipo AWS (TD-004:
¿cuentas separadas o una sola?). No inventar valores.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class StageConfig:
    stage: str
    account: str | None  # TODO §6.1: account ID por stage (None → cdk usa el del perfil actual)
    region: str  # TODO §6.1: confirmar region con el equipo AWS
    api_memory_mb: int
    worker_ai_timeout_s: int  # visibility_timeout de ai-jobs = 6x esto (regla cerrada)
    log_retention_days: int
    retain_data: bool  # prod: RemovalPolicy.RETAIN + deletion protection en tablas/bucket
    # Origenes desde los que el widget puede llamar a la API (CORS). El widget vive en la pagina
    # de VMC; en stage se abre mientras no haya un dominio de pruebas de VMC.
    cors_allowed_origins: str
    # Observabilidad (RNF-006): stage detallado, prod sobrio. `log_content` escribe una vista
    # previa del texto de los mensajes en los logs (nunca en prod: RF-052). `dev_observability`
    # enciende /dev/* (consola de widget/test.html), que solo muestra metricas de la propia
    # conversacion. Mismos nombres que core/config.py.
    log_level: str
    log_content: bool
    dev_observability: bool


_CONFIGS = {
    "stage": StageConfig(
        stage="stage",
        account=None,
        region="us-east-1",
        api_memory_mb=512,
        worker_ai_timeout_s=120,
        log_retention_days=14,
        retain_data=False,
        cors_allowed_origins="*",
        log_level="DEBUG",
        log_content=True,
        dev_observability=True,
    ),
    "prod": StageConfig(
        stage="prod",
        account=None,
        region="us-east-1",
        api_memory_mb=1024,
        worker_ai_timeout_s=120,
        log_retention_days=90,  # retencion de LOGS; la retencion de DATOS es D-014
        retain_data=True,
        cors_allowed_origins="https://www.vmcsubastas.com,https://vmcsubastas.com",
        log_level="INFO",
        log_content=False,
        dev_observability=False,
    ),
}


def get_config(stage: str) -> StageConfig:
    return _CONFIGS[stage]
