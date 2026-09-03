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

# Namespace fijo para derivar el advisor_id del cognito_sub (RF-006/D-021: un sub, un asesor).
# Cambiarlo "perderia" los asesores existentes — mismo patron que _USER_CONVERSATION_NAMESPACE
# en conversations/service.py.
_ADVISOR_NAMESPACE = uuid.UUID("9a7c2e4f-1d5b-4a8e-b3f0-6c9d2a5e7b14")


def advisor_id_for_cognito_sub(cognito_sub: str) -> str:
    """Id determinista del asesor (DETAILS.md §4.4 / Paso 5).

    Antes `advisor_id` era aleatorio: dos requests casi simultaneos del primer login de un
    mismo `cognito_sub` (dos pestañas, un doble-click) consultaban `find_by_cognito_sub` (GSI,
    eventualmente consistente), los dos veian "no existe" y los dos creaban una fila — el
    `attribute_not_exists(advisor_id)` de `create_advisor` nunca chocaba porque cada intento
    tenia un id distinto. Con el id derivado, chocan de verdad: gana uno solo.
    """
    return str(uuid.uuid5(_ADVISOR_NAMESPACE, f"cognito-sub:{cognito_sub}"))


class AdvisorDisabled(PermissionError):
    pass


def resolve_advisor(claims: CognitoClaims) -> Advisor:
    """El asesor de este request, dado de alta si es su primera vez, con `last_login_at` al dia."""
    now = utc_now_iso()
    advisor_id = advisor_id_for_cognito_sub(claims.sub)
    advisor = repository.get_advisor(advisor_id)
    if advisor is None:
        advisor = Advisor(
            advisor_id=advisor_id,
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
        # Otro request gano la carrera (mismo advisor_id determinista).
        advisor = repository.get_advisor(advisor_id)
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
