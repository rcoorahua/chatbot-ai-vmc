"""Emite un id token de asesor para probar `/advisor` en LOCAL (backend/api/dev_auth.py).

    python -m scripts.advisor_token --sub sub-ana-001 --email ana@vmc.test --name "Ana Torres"

Requiere `ADVISOR_DEV_AUTH=1` y `ADVISOR_DEV_JWT_SECRET` en `.env`. El payload imita los claims
que el authorizer de Cognito deja en el evento (`sub`, `email`, `name`, `cognito:username`,
`token_use`, `exp`), asi que lo que funciona con este token funciona con Cognito.

`sub-ana-001` y `sub-luis-002` existen en `scripts/seed_data.py`; cualquier otro `sub` se da de
alta solo al primer request (auto-alta, RF-006). Nunca sirve en AWS: alli el API Gateway solo
acepta tokens de Cognito.
"""

from __future__ import annotations

import argparse
import sys

from backend.core import auth
from backend.core.clock import epoch_seconds
from backend.core.config import get_settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Token de asesor para dev local")
    parser.add_argument("--sub", required=True, help="cognito_sub del asesor")
    parser.add_argument("--email", default=None)
    parser.add_argument("--name", default=None)
    parser.add_argument("--hours", type=int, default=8)
    args = parser.parse_args()

    settings = get_settings()
    if not settings.advisor_dev_auth or not settings.advisor_dev_jwt_secret:
        sys.exit("Falta ADVISOR_DEV_AUTH=1 y ADVISOR_DEV_JWT_SECRET en .env")

    payload = {
        "sub": args.sub,
        "cognito:username": args.sub,
        "token_use": "id",
        "exp": epoch_seconds() + args.hours * 3600,
    }
    if args.email:
        payload["email"] = args.email
    if args.name:
        payload["name"] = args.name
    print(auth.sign_jwt(payload, settings.advisor_dev_jwt_secret))


if __name__ == "__main__":
    main()
