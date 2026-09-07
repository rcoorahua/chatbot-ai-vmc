"""Como nacen y como se conservan los dos secretos del stack (PLAN.md §3, DETAILS.md §4.2).

No instancia el stack completo (bundlea las Lambdas con Docker, ortogonal a esto): replica los
dos secretos con la MISMA forma que infra/stacks/subastin_stack.py, contra la libreria real.

Lo que se fija aqui, y por que:

1. **En prod ningun secreto es DESTROY.** Si CloudFormation reemplaza el recurso (renombrarlo,
   cambiar como se genera), un DeletionPolicy Delete se lleva el `VMC_IDENTITY_SECRET` cargado
   a mano — que se comparte con VMC y no se puede regenerar solo — y el `SESSION_SIGNING_KEY`,
   cuyo cambio invalida TODAS las sesiones abiertas.
2. **El valor nunca es una propiedad de la plantilla.** Con `secret_object_value`, el JSON viaja
   en `SecretString` y CADA update del recurso vuelve a escribirlo: las claves vacias pisarian
   las API keys que alguien cargo con `put-secret-value`. `GenerateSecretString` solo se aplica
   al CREAR, que es justo lo que se quiere.
"""

import json

import aws_cdk as cdk
import pytest
from aws_cdk import RemovalPolicy
from aws_cdk import aws_secretsmanager as secretsmanager
from aws_cdk.assertions import Template


def _plantilla(retain_data: bool) -> Template:
    app = cdk.App()
    stack = cdk.Stack(app, "TestStack")
    removal = RemovalPolicy.RETAIN if retain_data else RemovalPolicy.DESTROY

    secretsmanager.Secret(
        stack,
        "IdentitySecret",
        secret_name="subastin-test-identity",
        removal_policy=removal,
        generate_secret_string=secretsmanager.SecretStringGenerator(
            secret_string_template=json.dumps({"VMC_IDENTITY_SECRET": ""}),
            generate_string_key="SESSION_SIGNING_KEY",
            password_length=48,
            exclude_punctuation=True,
        ),
    )
    secretsmanager.Secret(
        stack,
        "AiSecret",
        secret_name="subastin-test-ai",
        removal_policy=removal,
        generate_secret_string=secretsmanager.SecretStringGenerator(
            secret_string_template=json.dumps({"GEMINI_API_KEY": "", "PINECONE_API_KEY": ""}),
            generate_string_key="UNUSED_PLACEHOLDER",
            password_length=16,
            exclude_punctuation=True,
        ),
    )
    return Template.from_stack(stack)


def _secretos(template: Template) -> list[dict]:
    return list(template.find_resources("AWS::SecretsManager::Secret").values())


def test_en_prod_los_secretos_se_conservan():
    for recurso in _secretos(_plantilla(retain_data=True)):
        assert recurso["DeletionPolicy"] == "Retain"
        assert recurso["UpdateReplacePolicy"] == "Retain"


def test_en_stage_los_secretos_se_borran_con_el_stack():
    # stage es desechable a proposito: rehacerlo no debe dejar secretos huerfanos que cobran.
    for recurso in _secretos(_plantilla(retain_data=False)):
        assert recurso["DeletionPolicy"] == "Delete"


@pytest.mark.parametrize("retain_data", [True, False])
def test_el_valor_del_secreto_nunca_va_en_la_plantilla(retain_data):
    for recurso in _secretos(_plantilla(retain_data)):
        propiedades = recurso["Properties"]
        assert "SecretString" not in propiedades, (
            "el valor viajaria en la plantilla y cada update lo reescribiria"
        )
        assert "GenerateSecretString" in propiedades


def test_cada_secreto_nace_con_la_forma_que_espera_el_backend():
    # core/config._resolve_secrets_into_env vuelca las claves del JSON como variables de
    # entorno; si el secreto naciera como string suelto, cada cold start moriria con un
    # JSONDecodeError en vez de un "falta X" claro.
    plantillas = [
        set(json.loads(r["Properties"]["GenerateSecretString"]["SecretStringTemplate"]))
        for r in _secretos(_plantilla(retain_data=False))
    ]
    assert {"VMC_IDENTITY_SECRET"} in plantillas
    assert {"GEMINI_API_KEY", "PINECONE_API_KEY"} in plantillas
