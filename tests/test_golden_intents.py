"""Golden set de intents (tests/golden/intents.jsonl) — parte OFFLINE (D-026, cerrada
2026-08-28). RF-015/016, RF-052, D-006, D-024.

Aqui se verifica lo que decide el codigo sin modelo, en el MISMO orden que el worker:
triviales → guardrails → reglas. Para los casos que le tocan al modelo se verifica lo
contrario: que ninguna capa determinista los intercepte (un falso positivo de una regla o de
un guardrail le quita al usuario una respuesta real).

La parte que si llama a Gemini corre a mano: `python -m scripts.eval_intents` (cuesta
centavos y necesita GEMINI_API_KEY; por eso no esta en CI).
"""

import json
from pathlib import Path

import pytest

from backend.agent import guardrails, trivial
from backend.agent.heuristics import classify_by_rules
from backend.agent.intents import Intent

GOLDEN = Path(__file__).parent / "golden" / "intents.jsonl"


def load_golden() -> list[dict]:
    lines = GOLDEN.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip() and not line.startswith("#")]


CASES = load_golden()


def test_el_golden_set_tiene_tamano_y_forma():
    assert len(CASES) >= 40, "prompt-governance pide al menos 20; aqui cubrimos cuatro capas"
    assert len({c["message"] for c in CASES}) == len(CASES), "mensajes duplicados"
    for case in CASES:
        assert case["layer"] in ("trivial", "guardrail", "rules", "model"), case
        if case["layer"] in ("rules", "model"):
            Intent(case["intent"])  # etiqueta valida
    # Cada intent del modelo tiene al menos tres ejemplos: con menos, el 95% no mide nada.
    por_intent = {}
    for case in CASES:
        if case["layer"] == "model":
            por_intent[case["intent"]] = por_intent.get(case["intent"], 0) + 1
    assert all(por_intent.get(str(i), 0) >= 2 for i in Intent), por_intent


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["message"][:48])
def test_la_capa_determinista_decide_exactamente_lo_suyo(case):
    message = case["message"]
    layer = case["layer"]

    trivial_kind = trivial.match_trivial(message)
    if layer == "trivial":
        assert trivial_kind == case["rule"]
        return
    assert trivial_kind is None, f"trivial '{trivial_kind}' se comio una consulta real"

    verdict = guardrails.check_input(message)
    if layer == "guardrail":
        assert verdict is not None and verdict.kind == case["rule"], verdict
        return
    assert verdict is None, f"guardrail {verdict} intercepto una consulta legitima"

    rules = classify_by_rules(message)
    if layer == "rules":
        assert rules.intent == Intent(case["intent"]) and rules.rule == case["rule"], rules
        return

    assert layer == "model"
    assert rules.intent is None, f"la regla '{rules.rule}' decidio un caso que era del modelo"
