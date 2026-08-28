"""Eval REAL del enrutado contra el golden set (D-026, skill `prompt-governance`).

    python -m scripts.eval_intents                 # todo el golden set (~50 llamadas a flash-lite)
    python -m scripts.eval_intents --only model    # solo los casos que decide Gemini
    python -m scripts.eval_intents --show-all      # imprime tambien los aciertos

Recorre el golden set (`tests/golden/intents.jsonl`) en el MISMO orden que el worker:
triviales → guardrails → reglas → modelo. Las tres primeras capas no gastan nada; los casos
`model` llaman a Gemini de verdad (tier FAST, ~900 tokens de entrada cada uno): la corrida
completa cuesta alrededor de un centavo de dolar. Requiere `GEMINI_API_KEY` en `.env`.

Sale con codigo 1 si alguna capa determinista falla o si el acierto de los casos del modelo
queda por debajo del 95% (piso de prompt-governance). Ese es el criterio para mergear un cambio
en `agent/prompts.py` o en `heuristics.py`: correr esto antes y despues y comparar.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict

from backend.agent import guardrails, trivial
from backend.agent.classifier import classify
from backend.core import llm
from tests.test_golden_intents import load_golden

MODEL_FLOOR = 0.95


def main() -> None:
    parser = argparse.ArgumentParser(description="Eval del golden set de intents")
    parser.add_argument("--only", choices=["trivial", "guardrail", "rules", "model"])
    parser.add_argument("--show-all", action="store_true", help="imprime tambien los aciertos")
    args = parser.parse_args()

    cases = [c for c in load_golden() if not args.only or c["layer"] == args.only]
    if not cases:
        raise SystemExit("El golden set esta vacio para ese filtro")

    hits: dict[str, int] = defaultdict(int)
    totals: dict[str, int] = defaultdict(int)
    confusion: Counter[tuple[str, str]] = Counter()
    tokens_in = tokens_out = 0
    failures: list[str] = []

    for case in cases:
        expected_layer = case["layer"]
        totals[expected_layer] += 1
        actual_layer, actual, usage = _route(case["message"])
        tokens_in += usage.get("input", 0)
        tokens_out += usage.get("output", 0)

        expected = case["rule"] if expected_layer in ("trivial", "guardrail") else case["intent"]
        ok = actual_layer == expected_layer and actual == expected
        if expected_layer == "model" and actual_layer == "model":
            confusion[(case["intent"], actual)] += 1
        if ok:
            hits[expected_layer] += 1
            if args.show_all:
                print(f"  ok   [{expected_layer:9}] {case['message']!r} -> {actual}")
        else:
            failures.append(
                f"  FALLO [{expected_layer:9}] {case['message']!r}: esperaba {expected}, "
                f"salio {actual} (capa {actual_layer})"
            )

    print()
    for layer in ("trivial", "guardrail", "rules", "model"):
        if totals[layer]:
            print(f"{layer:9} {hits[layer]:3}/{totals[layer]:<3} "
                  f"{100 * hits[layer] / totals[layer]:5.1f}%")
    if failures:
        print("\nFallos:")
        print("\n".join(failures))

    if confusion:
        print("\nConfusion del modelo (esperado -> obtenido):")
        for (expected, actual), count in sorted(confusion.items()):
            marker = "" if expected == actual else "   <-- error"
            print(f"  {expected:8} -> {actual:8} {count:3}{marker}")

    spec = llm.model_for(llm.ModelTier.FAST)
    cost = (tokens_in * spec.input_usd_per_million + tokens_out * spec.output_usd_per_million) / 1e6
    print(f"\nTokens: {tokens_in} entrada / {tokens_out} salida ({spec.name}) "
          f"≈ US$ {cost:.4f}")

    deterministic_failed = any(
        totals[layer] and hits[layer] != totals[layer]
        for layer in ("trivial", "guardrail", "rules")
    )
    model_rate = hits["model"] / totals["model"] if totals["model"] else 1.0
    if deterministic_failed:
        print("\nRESULTADO: una capa determinista fallo. Eso lo cubre pytest; revisar antes.")
        sys.exit(1)
    if model_rate < MODEL_FLOOR:
        print(f"\nRESULTADO: el modelo acerto {100 * model_rate:.1f}% "
              f"(piso {100 * MODEL_FLOOR:.0f}%). No mergear el cambio de prompt.")
        sys.exit(1)
    print(f"\nRESULTADO: OK ({100 * model_rate:.1f}% del modelo sobre el piso "
          f"de {100 * MODEL_FLOOR:.0f}%).")


def _route(message: str) -> tuple[str, str, dict[str, int]]:
    """Reproduce el orden del worker y devuelve (capa que decidio, decision, uso)."""
    kind = trivial.match_trivial(message)
    if kind:
        return "trivial", kind, {}
    verdict = guardrails.check_input(message)
    if verdict is not None:
        return "guardrail", verdict.kind, {}
    result = classify(message)
    if result.source == "rules":
        return "rules", str(result.intent), {}
    return "model", str(result.intent), result.usage or {}


if __name__ == "__main__":
    main()
