"""Resolver al asesor a partir de los claims de Cognito (RF-006/RF-007).

Regla (Aaron, 2026-08-27): **auto-alta al primer login**. Cognito solo emite tokens a quien fue
invitado (RF-006), asi que la invitacion ya es el control de acceso; exigir ademas una fila
creada a mano seria una segunda lista que nadie administra (no hay panel, RF-049). El asesor
nuevo nace ACTIVE con nombre/correo de los claims. INVITED pasa a ACTIVE al entrar; DISABLED
se rechaza aunque Cognito siga emitiendo tokens.
"""

import uuid

from backend.advisors import repository
from backend.advisors.models import Advisor, AdvisorStatus
from backend.core.auth import CognitoClaims
from backend.core.clock import utc_now_iso


class AdvisorDisabled(PermissionError):
    pass


def resolve_advisor(claims: CognitoClaims) -> Advisor:
    """El asesor de este request, dado de alta si es su primera vez, con `last_login_at` al dia."""
    now = utc_now_iso()
    advisor = repository.find_by_cognito_sub(claims.sub)
    if advisor is None:
        advisor = Advisor(
            advisor_id=f"adv_{uuid.uuid4().hex[:12]}",
            cognito_sub=claims.sub,
            name=claims.name,
            email=claims.email,
            status=AdvisorStatus.ACTIVE,
            created_at=now,
            updated_at=now,
            last_login_at=now,
        )
        if repository.create_advisor(advisor):
            return advisor
        advisor = repository.find_by_cognito_sub(claims.sub)
        if advisor is None:  # pragma: no cover — solo si se borra entre dos lecturas
            raise LookupError(claims.sub)

    if advisor.status == AdvisorStatus.DISABLED:
        raise AdvisorDisabled(advisor.advisor_id)

    repository.record_login(
        advisor.advisor_id,
        at=now,
        status=AdvisorStatus.ACTIVE,
        name=claims.name,
        email=claims.email,
    )
    return advisor.model_copy(
        update={
            "status": AdvisorStatus.ACTIVE,
            "name": claims.name or advisor.name,
            "email": claims.email or advisor.email,
            "last_login_at": now,
            "updated_at": now,
        }
    )
