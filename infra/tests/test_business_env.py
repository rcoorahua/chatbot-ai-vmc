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


def test_anon_session_limit_matches_paso_11_no_es_cero():
    # DETAILS.md §4.9/Paso 11: en dev el default es 0 (sin tope); stage/prod deben encenderlo.
    assert int(BUSINESS_ENV["ANON_SESSIONS_PER_IP_PER_DAY"]) > 0


def _env_example() -> dict[str, str]:
    """`.env.example` (raiz del repo) como dict: es la fuente de los valores de dev."""
    values = {}
    example = Path(__file__).resolve().parents[2] / ".env.example"
    for line in example.read_text("utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    return values


def test_rag_calibration_matches_env_example():
    # CLAUDE.md "RAG": el umbral y el margen estan calibrados contra el indice real; si se
    # recalibran en .env.example, stage tiene que recibir el mismo numero (auditoria 2026-09-06).
    example = _env_example()
    for key in ("RAG_TOP_K", "RAG_MIN_SCORE", "RAG_SIBLING_MARGIN", "PINECONE_INDEX_NAME",
                "PINECONE_NAMESPACE"):
        assert BUSINESS_ENV[key] == example[key], key


if __name__ == "__main__":
    test_message_length_matches_d005()
    test_ai_quota_matches_d027_business_numbers()
    test_every_value_is_a_string()
    test_anon_session_limit_matches_paso_11_no_es_cero()
    test_rag_calibration_matches_env_example()
    print("ok")
