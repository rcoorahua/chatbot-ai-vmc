"""Entry point CDK. Un stack por stage, mismo codigo (T4/T5).

    cdk synth  -c stage=stage
    cdk deploy -c stage=stage
    cdk watch  -c stage=stage      # hotswap de codigo Lambda (~3 s); infra = deploy completo
    cdk deploy -c stage=prod

dev NO se despliega: corre local con docker-compose (dynamodb-local + localstack).
Requiere `cdk bootstrap aws://<account>/<region>` una vez por cuenta+region (PLAN.md §6).
"""

import aws_cdk as cdk
from config import get_config
from stacks.subastin_stack import SubastinStack

app = cdk.App()

stage = app.node.try_get_context("stage")
if stage not in ("stage", "prod"):
    raise ValueError(
        "Falta el stage: usa  cdk <cmd> -c stage=stage|prod  (dev es local, no se despliega)"
    )

cfg = get_config(stage)

SubastinStack(
    app,
    f"subastin-{stage}",
    cfg=cfg,
    # account/region llegan del equipo AWS (PLAN.md §6.1) — completar en config.py.
    env=cdk.Environment(account=cfg.account, region=cfg.region),
)

app.synth()
