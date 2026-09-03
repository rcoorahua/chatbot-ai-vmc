"""Prueba aislada del fix DETAILS.md §4.9 / Paso 11 ("Throttling Gateway/WAF").

No instancia el stack completo: PythonFunction bundlea con Docker (requiere el daemon
corriendo) y eso es ortogonal a lo que se prueba aqui. Replica solo el HttpApi + stage con la
MISMA forma que infra/stacks/subastin_stack.py, contra la libreria real de aws-cdk-lib, y
verifica que el stage $default trae throttle explicito (freno global barato, sin WAF, que
complementa -- no reemplaza -- los topes por IP/usuario de agent/quota.py).
"""

import aws_cdk as cdk
from aws_cdk import aws_apigatewayv2 as apigwv2
from aws_cdk import aws_apigatewayv2_integrations as integrations
from aws_cdk import aws_lambda as lambda_
from aws_cdk.assertions import Template


def _synth_template() -> Template:
    app = cdk.App()
    stack = cdk.Stack(app, "TestStack")

    fn = lambda_.Function(
        stack,
        "Fn",
        runtime=lambda_.Runtime.PYTHON_3_12,
        handler="index.handler",
        code=lambda_.Code.from_inline("def handler(event, context): return {}"),
    )
    http_api = apigwv2.HttpApi(stack, "HttpApi", create_default_stage=False)
    apigwv2.HttpRoute(
        stack,
        "DefaultRoute",
        http_api=http_api,
        route_key=apigwv2.HttpRouteKey.DEFAULT,
        integration=integrations.HttpLambdaIntegration("Integ", fn),
    )
    apigwv2.HttpStage(
        stack,
        "DefaultStage",
        http_api=http_api,
        stage_name="$default",
        auto_deploy=True,
        throttle=apigwv2.ThrottleSettings(rate_limit=50, burst_limit=100),
    )
    return Template.from_stack(stack)


def test_el_stage_default_trae_throttle_explicito():
    template = _synth_template()
    template.has_resource_properties(
        "AWS::ApiGatewayV2::Stage",
        {
            "StageName": "$default",
            "AutoDeploy": True,
            "DefaultRouteSettings": {
                "ThrottlingRateLimit": 50,
                "ThrottlingBurstLimit": 100,
            },
        },
    )


if __name__ == "__main__":
    test_el_stage_default_trae_throttle_explicito()
    print("ok")
