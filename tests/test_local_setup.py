"""El entorno local espeja lo que el stack define para las colas (CLAUDE.md, invariantes).

Regla cerrada: `visibility_timeout` de cada cola >= 6x el timeout de su worker. El stack la
cumplia (720 s / 180 s) pero `local_setup` creaba las colas con el default de SQS (30 s): un
job de IA que tardara mas se reentregaba a medio procesar y el bot respondia DOS veces la
misma pregunta (2026-09-08, medido en AIUsage: dos CLASSIFICATION y dos RESPONSE del mismo
message_id, 32 s aparte). El esquema de tablas ya tenia esta guarda; las colas no.
"""

import importlib.util
import os
from pathlib import Path

import pytest

from scripts import local_setup

_REPO = Path(__file__).resolve().parents[1]


def _infra_config():
    """`infra/config.py` no depende de aws_cdk: se importa por ruta, sin meter `infra/` en
    sys.path (un modulo top-level llamado `config` chocaria con cualquier otro)."""
    spec = importlib.util.spec_from_file_location("infra_config", _REPO / "infra" / "config.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_las_colas_locales_espejan_la_regla_del_stack():
    cfg = _infra_config()
    ai_jobs, notifications = local_setup.nombres_de_cola()

    for stage in ("stage", "prod"):
        esperado = cfg.VISIBILITY_FACTOR * cfg.get_config(stage).worker_ai_timeout_s
        assert local_setup.VISIBILITY_TIMEOUT_S[ai_jobs] == esperado, stage
    assert local_setup.VISIBILITY_TIMEOUT_S[notifications] == (
        cfg.VISIBILITY_FACTOR * cfg.WORKER_NOTIFY_TIMEOUT_S
    )


def _sqs_o_skip():
    sqs = local_setup.cliente_sqs()
    try:
        sqs.list_queues()
    except Exception as error:  # noqa: BLE001 — cualquier fallo de red = no esta arriba
        if os.environ.get("CI"):
            pytest.fail(f"LocalStack no responde en CI: {error}")
        pytest.skip("LocalStack no esta arriba — levantarlo con: docker compose up -d")
    return sqs


def test_local_setup_aplica_el_visibility_timeout_a_colas_que_ya_existen():
    # create_queue es idempotente pero no toca atributos: si la cola ya existia con el default
    # (30 s), solo set_queue_attributes la corrige. Correrlo dos veces tiene que converger.
    sqs = _sqs_o_skip()
    local_setup.crear_colas_y_bucket(verbose=False)
    local_setup.crear_colas_y_bucket(verbose=False)

    endpoint = local_setup._env("SQS_ENDPOINT_URL", "http://localhost:4566")
    for cola, segundos in local_setup.VISIBILITY_TIMEOUT_S.items():
        attrs = sqs.get_queue_attributes(
            QueueUrl=f"{endpoint}/000000000000/{cola}", AttributeNames=["VisibilityTimeout"]
        )["Attributes"]
        assert attrs["VisibilityTimeout"] == str(segundos), cola
