"""Base comun de los modelos que se guardan en DynamoDB.

Vive en `core` porque la usan varios dominios (`conversations`, `advisors`) y la regla de
dependencias de backend/__init__.py prohibe que un dominio importe a otro solo por esto.

`to_item()` omite los None a proposito: un atributo ausente no entra a los GSI (una
conversacion anonima sin `user_id` no aparece en `gsi1_user`), mientras que un NULL explicito
si ocuparia espacio y confundiria a las consultas.
"""

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict


def from_dynamo(value: Any) -> Any:
    """boto3 devuelve todos los numeros como Decimal; los modelos quieren int/float."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {key: from_dynamo(item) for key, item in value.items()}
    if isinstance(value, list):
        return [from_dynamo(item) for item in value]
    return value


class DynamoModel(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    def to_item(self) -> dict[str, Any]:
        return self.model_dump(exclude_none=True)

    @classmethod
    def from_item(cls, item: dict[str, Any]):
        return cls.model_validate(from_dynamo(item))
