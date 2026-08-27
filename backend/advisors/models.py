"""Modelo Pydantic Advisor (PLAN.md §4, RF-006/RF-007).

`status`: INVITED (existe en Cognito, nunca entro) → ACTIVE (ya inicio sesion) → DISABLED
(baja: el JWT puede seguir siendo valido hasta que se borre en Cognito, asi que el backend
tambien lo rechaza). `role` solo tiene ADVISOR en el MVP (RF-007) pero existe para crecer.
"""

from enum import StrEnum

from backend.core.dynamo_model import DynamoModel


class AdvisorStatus(StrEnum):
    INVITED = "INVITED"
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class AdvisorRole(StrEnum):
    ADVISOR = "ADVISOR"


class Advisor(DynamoModel):
    advisor_id: str
    cognito_sub: str
    name: str | None = None
    email: str | None = None
    role: AdvisorRole = AdvisorRole.ADVISOR
    status: AdvisorStatus = AdvisorStatus.ACTIVE
    created_at: str
    updated_at: str
    last_login_at: str | None = None
