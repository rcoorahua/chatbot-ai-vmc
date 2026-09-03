"""Resolucion de secretos en runtime (DETAILS.md §4.2): en AWS cada Lambda recibe el ARN de
solo los secretos que consume y `get_settings()` los resuelve de Secrets Manager antes de
construir `Settings`. En dev esos ARN no existen y no debe intentarse ninguna llamada a AWS."""

import json

from backend.core.config import get_settings, reset_settings


def test_sin_arn_de_secreto_get_settings_no_llama_a_aws(monkeypatch):
    monkeypatch.delenv("IDENTITY_SECRET_ARN", raising=False)
    monkeypatch.delenv("AI_SECRET_ARN", raising=False)

    def _fallar_si_se_llama(*args, **kwargs):
        raise AssertionError("boto3.client no debia llamarse sin *_SECRET_ARN en el entorno")

    monkeypatch.setattr("boto3.client", _fallar_si_se_llama)
    reset_settings()
    try:
        get_settings()
    finally:
        reset_settings()


def test_resuelve_identity_secret_arn_a_variables_de_entorno(monkeypatch):
    arn = "arn:aws:secretsmanager:us-east-1:111111111111:secret:fake-identity"

    class _FakeSecretsClient:
        def get_secret_value(self, SecretId):
            assert SecretId == arn
            return {"SecretString": json.dumps({"VMC_IDENTITY_SECRET": "del-secreto"})}

    monkeypatch.setattr("boto3.client", lambda *a, **k: _FakeSecretsClient())
    monkeypatch.setenv("IDENTITY_SECRET_ARN", arn)
    monkeypatch.delenv("VMC_IDENTITY_SECRET", raising=False)
    reset_settings()
    try:
        assert get_settings().vmc_identity_secret == "del-secreto"
    finally:
        monkeypatch.delenv("VMC_IDENTITY_SECRET", raising=False)
        reset_settings()
