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


_CONFIGS = {
    "stage": StageConfig(
        stage="stage",
        account=None,
        region="us-east-1",
        api_memory_mb=512,
        worker_ai_timeout_s=120,
        log_retention_days=14,
        retain_data=False,
    ),
    "prod": StageConfig(
        stage="prod",
        account=None,
        region="us-east-1",
        api_memory_mb=1024,
        worker_ai_timeout_s=120,
        log_retention_days=90,  # retencion de LOGS; la retencion de DATOS es D-014
        retain_data=True,
    ),
}


def get_config(stage: str) -> StageConfig:
    return _CONFIGS[stage]
