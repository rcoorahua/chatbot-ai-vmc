"""UNICO lugar que conoce claves/GSI de Advisors: PK `advisor_id` (derivado de `cognito_sub`,
ver `advisors.service.advisor_id_for_cognito_sub`, DETAILS.md §4.4 / Paso 5). El GSI
`gsi_cognito` sigue en el esquema (infra/local_setup) para inspeccion manual, pero ningun
codigo lo consulta: con el id determinista, resolver por PK es directo y fuertemente
consistente — no hace falta pasar por el GSI."""

from botocore.exceptions import ClientError

from backend.advisors.models import Advisor
from backend.core.aws import dynamodb_resource
from backend.core.config import get_settings


def _table():
    return dynamodb_resource().Table(get_settings().table_advisors)


def get_advisor(advisor_id: str) -> Advisor | None:
    # ConsistentRead: es el chequeo de existencia en resolve_advisor (DETAILS.md §4.4 / Paso 5)
    # — tiene que ver la escritura del otro request de la carrera al instante.
    item = _table().get_item(Key={"advisor_id": advisor_id}, ConsistentRead=True).get("Item")
    return Advisor.from_item(item) if item else None


def create_advisor(advisor: Advisor) -> bool:
    """Alta condicional. Solo evita dos filas si `advisor.advisor_id` es determinista
    (`advisor_id_for_cognito_sub`, DETAILS.md §4.4 / Paso 5) — con un id aleatorio, dos
    intentos concurrentes generan ids distintos y la condicion nunca choca entre ellos."""
    try:
        _table().put_item(
            Item=advisor.to_item(), ConditionExpression="attribute_not_exists(advisor_id)"
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise
    return True


def record_login(
    advisor_id: str, *, at: str, status: str, name: str | None, email: str | None
) -> None:
    """Marca el acceso y refresca nombre/correo desde los claims (Cognito manda sobre la copia)."""
    sets = ["last_login_at = :at", "updated_at = :at", "#status = :status"]
    values = {":at": at, ":status": status}
    names = {"#status": "status"}
    if name:
        sets.append("#name = :name")
        values[":name"] = name
        names["#name"] = "name"
    if email:
        sets.append("email = :email")
        values[":email"] = email
    _table().update_item(
        Key={"advisor_id": advisor_id},
        UpdateExpression="SET " + ", ".join(sets),
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
    )
