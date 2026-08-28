"""UNICO lugar que conoce claves/GSI de Advisors: PK `advisor_id`, GSI `gsi_cognito` por
`cognito_sub` (sin SK: un sub de Cognito es un solo asesor)."""

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from backend.advisors.models import Advisor
from backend.core.aws import dynamodb_resource
from backend.core.config import get_settings


def _table():
    return dynamodb_resource().Table(get_settings().table_advisors)


def get_advisor(advisor_id: str) -> Advisor | None:
    item = _table().get_item(Key={"advisor_id": advisor_id}).get("Item")
    return Advisor.from_item(item) if item else None


def find_by_cognito_sub(cognito_sub: str) -> Advisor | None:
    response = _table().query(
        IndexName="gsi_cognito",
        KeyConditionExpression=Key("cognito_sub").eq(cognito_sub),
        Limit=1,
    )
    items = response["Items"]
    return Advisor.from_item(items[0]) if items else None


def create_advisor(advisor: Advisor) -> bool:
    """Alta condicional: dos requests simultaneos del mismo asesor nuevo no crean dos filas."""
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
