"""DETAILS.md Paso 4: "local, stage y documentacion usan los mismos limites intencionales".

BUSINESS_ENV es un dict de modulo (sin objetos CDK), asi que se importa e inspecciona sin
sintetizar el stack ni bundlear nada — no requiere Docker. Fija en un solo lugar los valores
que ya se desviaron una vez (MAX_MESSAGE_CHARS quedo en "2000" en el stack mientras
core/config.py ya decia 500, D-005) para que una regresion similar falle aqui, no en stage.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stacks.subastin_stack import BUSINESS_ENV  # noqa: E402


def test_message_length_matches_d005():
    # D-005 (revisada 2026-08-31): 500, no los 2000 originales.
    assert BUSINESS_ENV["MAX_MESSAGE_CHARS"] == "500"


def test_ai_quota_matches_d027_business_numbers():
    # D-027: autenticado es el doble que anonimo, por hora y por dia.
    assert BUSINESS_ENV["AI_QUOTA_ANON_PER_HOUR"] == "10"
    assert BUSINESS_ENV["AI_QUOTA_ANON_PER_DAY"] == "20"
    assert BUSINESS_ENV["AI_QUOTA_AUTH_PER_HOUR"] == "20"
    assert BUSINESS_ENV["AI_QUOTA_AUTH_PER_DAY"] == "40"
    for key in ("AI_QUOTA_ANON_PER_HOUR", "AI_QUOTA_AUTH_PER_HOUR"):
        assert int(BUSINESS_ENV[key]) * 2 == int(BUSINESS_ENV[key.replace("PER_HOUR", "PER_DAY")])


def test_every_value_is_a_string():
    # Env vars de Lambda son siempre string; un int aqui rompe el synth con un error crudo.
    assert all(isinstance(v, str) for v in BUSINESS_ENV.values())


if __name__ == "__main__":
    test_message_length_matches_d005()
    test_ai_quota_matches_d027_business_numbers()
    test_every_value_is_a_string()
    print("ok")
