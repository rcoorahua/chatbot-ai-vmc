"""Prueba aislada del fix DETAILS.md §4.3 (preflight CORS bloqueado por el authorizer de Cognito).

No instancia el stack completo: PythonFunction bundlea con Docker (requiere el daemon corriendo)
y eso es ortogonal a lo que se prueba aqui. Replica solo el HttpApi + authorizer + ruta protegida
con la MISMA forma que infra/stacks/subastin_stack.py, contra la libreria real de aws-cdk-lib, y
verifica el mecanismo: CORS_PREFLIGHT en el nivel de API responde OPTIONS sin pasar por rutas ni
authorizer, mientras la ruta real (ANY) sigue exigiendo el JWT.
"""

import aws_cdk as cdk
from aws_cdk import aws_apigatewayv2 as apigwv2
from aws_cdk import aws_apigatewayv2_authorizers as authorizers
from aws_cdk import aws_apigatewayv2_integrations as integrations
from aws_cdk import aws_cognito as cognito
from aws_cdk import aws_lambda as lambda_
from aws_cdk.assertions import Match, Template


def _synth_template() -> Template:
    app = cdk.App()
    stack = cdk.Stack(app, "TestStack")

    user_pool = cognito.UserPool(stack, "Pool")
    user_pool_client = user_pool.add_client("Client")

    fn = lambda_.Function(
        stack,
        "Fn",
        runtime=lambda_.Runtime.PYTHON_3_12,
        handler="index.handler",
        code=lambda_.Code.from_inline("def handler(event, context): return {}"),
    )

    http_api = apigwv2.HttpApi(
        stack,
        "HttpApi",
        cors_preflight=apigwv2.CorsPreflightOptions(
            allow_origins=["https://www.vmcsubastas.com"],
            allow_methods=[
                apigwv2.CorsHttpMethod.GET,
                apigwv2.CorsHttpMethod.POST,
                apigwv2.CorsHttpMethod.PATCH,
            ],
            allow_headers=["Authorization", "Content-Type"],
        ),
    )
    cognito_authorizer = authorizers.HttpJwtAuthorizer(
        "CognitoAuthorizer",
        f"https://cognito-idp.us-east-1.amazonaws.com/{user_pool.user_pool_id}",
        jwt_audience=[user_pool_client.user_pool_client_id],
    )
    http_api.add_routes(
        path="/advisor/{proxy+}",
        integration=integrations.HttpLambdaIntegration("Integ", fn),
        authorizer=cognito_authorizer,
    )
    return Template.from_stack(stack)


def test_api_level_cors_covers_patch_and_declared_origin():
    template = _synth_template()
    template.has_resource_properties(
        "AWS::ApiGatewayV2::Api",
        {
            "CorsConfiguration": {
                "AllowMethods": Match.array_with(["GET", "POST", "PATCH"]),
                "AllowOrigins": ["https://www.vmcsubastas.com"],
                "AllowHeaders": Match.array_with(["Authorization"]),
            }
        },
    )


def test_advisor_route_stays_a_single_any_route_guarded_by_the_authorizer():
    # Si CDK generase una ruta OPTIONS aparte para /advisor, volveria a exponerla al mismo
    # authorizer (o a uno nuevo) y el bug original reaparece. Con cors_preflight, la unica ruta
    # es "ANY /advisor/{proxy+}": el preflight lo resuelve API Gateway antes de llegar a rutas.
    template = _synth_template()
    routes = template.find_resources("AWS::ApiGatewayV2::Route")
    advisor_routes = [
        r for r in routes.values() if r["Properties"]["RouteKey"] == "ANY /advisor/{proxy+}"
    ]
    assert len(advisor_routes) == 1
    assert advisor_routes[0]["Properties"]["AuthorizationType"] == "JWT"
    assert not any(
        r["Properties"]["RouteKey"].startswith("OPTIONS ") for r in routes.values()
    )


if __name__ == "__main__":
    test_api_level_cors_covers_patch_and_declared_origin()
    test_advisor_route_stays_a_single_any_route_guarded_by_the_authorizer()
    print("ok")
