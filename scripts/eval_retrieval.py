"""Benchmark de RECUPERACION contra Pinecone real (RF-017 / RF-018 / RB-009). Sin Gemini.

    python -m scripts.eval_retrieval                     # todo el golden set con la config vigente
    python -m scripts.eval_retrieval --only errata       # una categoria
    python -m scripts.eval_retrieval --threshold 0.82    # probar otro RAG_MIN_SCORE sin tocar .env
    python -m scripts.eval_retrieval --margin 0          # sin expansion por tema
    python -m scripts.eval_retrieval --rerank            # EXPERIMENTAL: reranker de Pinecone
    python -m scripts.eval_retrieval --show-all --json out.json

Recorre `tests/golden/retrieval.jsonl` (ver BENCHMARK.md) y para cada consulta llama a
`rag.retrieve()` tal como lo hace el worker: misma expansion por tema, mismo umbral. Mide dos
cosas y las reporta por categoria:

  recall   de los casos CON respuesta en el corpus, cuantos dejan al redactor evidencia del
           articulo correcto (algun fragmento relevante con ese `topic`);
  rechazo  de los casos SIN respuesta (`sin_respuesta`, `ajena`), cuantos quedan con cero
           evidencia — el que se cuela le da al redactor material para inventar (RB-009).

Ademas separa "el articulo no aparece entre los candidatos" (problema del embedding) de "aparece
pero bajo el umbral" (problema del umbral): son arreglos distintos. Cuesta una consulta a
Pinecone por caso (~110), cero llamadas a Gemini; no requiere GEMINI_API_KEY.

`--rerank` NO cambia el pipeline: vuelve a puntuar los candidatos con un cross-encoder alojado
en Pinecone (`pc.inference.rerank`) y decide con `--rerank-threshold`. Sirve para calibrar antes
de decidir si entra al worker (BENCHMARK.md §4).

Sale con codigo 1 si recall o rechazo quedan por debajo de los pisos (`RECALL_FLOOR`,
`REJECT_FLOOR`): ese es el criterio de regresion al tocar el corpus, el indice, el umbral o
`agent/rag.py`. Los pisos se fijan un poco por debajo de la linea base medida.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass

from backend.agent import rag
from backend.core.config import get_settings
from tests.test_golden_retrieval import KINDS, NEGATIVE_KINDS, load_golden

# Linea base del 2026-09-03 (BENCHMARK.md §3): recall 84% y rechazo 90% con e5 + 0.84 + 0.04.
# Los pisos van un poco por debajo: un caso nuevo dificil no debe "romper" el benchmark, una
# regresion de verdad (indice recreado con otro modelo, umbral movido a ciegas) si.
RECALL_FLOOR = 0.78
REJECT_FLOOR = 0.85

DEFAULT_RERANK_MODEL = "bge-reranker-v2-m3"
DEFAULT_RERANK_THRESHOLD = 0.30
RERANK_CANDIDATES = 8


@dataclass
class Outcome:
    query: str
    kind: str
    expected: list[str]
    ok: bool
    # evidencia_correcta | sin_evidencia | tema_equivocado | se_cuela | rechazada
    verdict: str
    best_score: float
    # Mejor score del articulo esperado entre los candidatos (None = ni aparecio).
    best_expected_score: float | None
    evidence_topics: list[str]
    siblings: int


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    parser = argparse.ArgumentParser(description="Benchmark de recuperacion (Pinecone, sin Gemini)")
    parser.add_argument("--only", help="categoria: " + ", ".join(sorted(KINDS)))
    parser.add_argument("--threshold", type=float, help="RAG_MIN_SCORE a probar (default: .env)")
    parser.add_argument("--margin", type=float, help="RAG_SIBLING_MARGIN a probar (default: .env)")
    parser.add_argument("--rerank", nargs="?", const=DEFAULT_RERANK_MODEL, default=None,
                        metavar="MODELO", help="EXPERIMENTAL: decidir con un reranker de Pinecone")
    parser.add_argument("--rerank-threshold", type=float, default=DEFAULT_RERANK_THRESHOLD)
    parser.add_argument("--show-all", action="store_true", help="imprime tambien los aciertos")
    parser.add_argument("--json", metavar="ARCHIVO", help="guarda cada caso con sus scores")
    args = parser.parse_args()

    settings = get_settings()
    if args.margin is not None:
        settings.rag_sibling_margin = args.margin
    threshold = args.threshold if args.threshold is not None else settings.rag_min_score

    cases = [c for c in load_golden() if not args.only or c["kind"] == args.only]
    if not cases:
        raise SystemExit("El golden set esta vacio para ese filtro")

    reranker = _Reranker(args.rerank, args.rerank_threshold) if args.rerank else None
    if reranker:
        mode = (f"reranker {args.rerank} · umbral {args.rerank_threshold} · "
                f"{RERANK_CANDIDATES} candidatos")
    else:
        mode = f"e5 · umbral {threshold} · margen por tema {settings.rag_sibling_margin}"
    print(f"Indice '{settings.pinecone_index_name}/{settings.pinecone_namespace}' · {mode}")
    print(f"{len(cases)} casos\n")

    outcomes: list[Outcome] = []
    for case in cases:
        outcome = reranker.judge(case) if reranker else _judge(case, threshold)
        outcomes.append(outcome)
        if args.show_all or not outcome.ok:
            _print(outcome)

    _summary(outcomes)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump([asdict(o) for o in outcomes], fh, ensure_ascii=False, indent=1)
        print(f"\nDetalle guardado en {args.json}")

    recall, reject = _rates(outcomes)
    failed = (recall is not None and recall < RECALL_FLOOR) or (
        reject is not None and reject < REJECT_FLOOR)
    if failed:
        print(f"\nFALLO: por debajo de los pisos "
              f"(recall ≥ {RECALL_FLOOR:.0%}, rechazo ≥ {REJECT_FLOOR:.0%})")
        raise SystemExit(1)
    print("\nOK: dentro de los pisos")


# ───────────────────────── juicio de un caso ─────────────────────────


def _judge(case: dict, threshold: float) -> Outcome:
    """Mismo camino que el worker: `rag.retrieve` con umbral y expansion por tema."""
    result = rag.retrieve(case["query"], min_score=threshold)
    return _outcome(case, evidence=result.relevant, candidates=result.all_fragments)


def _outcome(
    case: dict, *, evidence: list[rag.Fragment], candidates: list[rag.Fragment]
) -> Outcome:
    expected = case["topics"]
    evidence_topics = [f.topic for f in evidence]
    best = max((f.score for f in candidates), default=0.0)
    best_expected = max((f.score for f in candidates if f.topic in expected), default=None)
    negative = case["kind"] in NEGATIVE_KINDS

    if negative:
        ok = not evidence
        verdict = "rechazada" if ok else "se_cuela"
    elif any(t in expected for t in evidence_topics):
        ok, verdict = True, "evidencia_correcta"
    elif evidence:
        ok, verdict = False, "tema_equivocado"
    else:
        ok, verdict = False, "sin_evidencia"
    return Outcome(
        query=case["query"], kind=case["kind"], expected=expected, ok=ok, verdict=verdict,
        best_score=best, best_expected_score=best_expected, evidence_topics=evidence_topics,
        siblings=sum(1 for f in evidence if f.sibling),
    )


class _Reranker:
    """Puntua los candidatos con un cross-encoder alojado en Pinecone. Solo para calibrar."""

    def __init__(self, model: str, threshold: float) -> None:
        from pinecone import Pinecone

        self.model = model
        self.threshold = threshold
        self.client = Pinecone(api_key=get_settings().pinecone_api_key)

    def judge(self, case: dict) -> Outcome:
        candidates = rag.retrieve(
            case["query"], min_score=0.0, top_k=RERANK_CANDIDATES
        ).all_fragments
        if not candidates:
            return _outcome(case, evidence=[], candidates=[])
        docs = [{"id": str(i), "text": f.text} for i, f in enumerate(candidates)]
        ranked = self.client.inference.rerank(
            model=self.model, query=case["query"], documents=docs, rank_fields=["text"],
            top_n=len(docs), return_documents=False,
        )
        rescored = [
            rag.Fragment(text=candidates[int(r.index)].text, score=float(r.score),
                         topic=candidates[int(r.index)].topic,
                         source_url=candidates[int(r.index)].source_url)
            for r in ranked.data
        ]
        top_k = get_settings().rag_top_k
        evidence = [f for f in rescored if f.score >= self.threshold][:top_k]
        return _outcome(case, evidence=evidence, candidates=rescored)


# ───────────────────────── reporte ─────────────────────────


def _print(outcome: Outcome) -> None:
    mark = "OK " if outcome.ok else "XX "
    expected = "; ".join(t[:38] for t in outcome.expected) or "(nada)"
    got = "; ".join(t[:38] for t in outcome.evidence_topics) or "(sin evidencia)"
    line = (f"{mark}[{outcome.kind}] {outcome.query!r} → {outcome.verdict}  "
            f"mejor {outcome.best_score:.3f}")
    if outcome.best_expected_score is not None and outcome.verdict != "evidencia_correcta":
        line += f" · esperado {outcome.best_expected_score:.3f}"
    if outcome.siblings:
        line += f" · {outcome.siblings} por tema"
    print(line)
    if not outcome.ok:
        print(f"      esperaba: {expected}\n      evidencia: {got}")


def _summary(outcomes: list[Outcome]) -> None:
    by_kind: dict[str, list[Outcome]] = defaultdict(list)
    for o in outcomes:
        by_kind[o.kind].append(o)
    print("\n" + "─" * 72)
    print(f"{'categoria':14} {'casos':>5} {'ok':>4} {'tasa':>6}   fallos")
    for kind, items in by_kind.items():
        ok = sum(1 for o in items if o.ok)
        verdicts = defaultdict(int)
        for o in items:
            if not o.ok:
                verdicts[o.verdict] += 1
        detail = ", ".join(f"{v} {k}" for k, v in verdicts.items()) or "-"
        print(f"{kind:14} {len(items):>5} {ok:>4} {ok / len(items):>6.0%}   {detail}")
    recall, reject = _rates(outcomes)
    positives = [o for o in outcomes if o.kind not in NEGATIVE_KINDS]
    missing = [o for o in positives if o.verdict == "sin_evidencia"]
    under = sum(1 for o in missing if o.best_expected_score is not None)
    absent = len(missing) - under
    print("─" * 72)
    if recall is not None:
        print(f"recall  (con respuesta, evidencia del articulo correcto): {recall:.1%}")
        print(f"        sin evidencia con el articulo entre los candidatos: {under}  ·  "
              f"articulo ausente de los candidatos: {absent}")
    if reject is not None:
        print(f"rechazo (sin respuesta, cero evidencia):                  {reject:.1%}")


def _rates(outcomes: list[Outcome]) -> tuple[float | None, float | None]:
    positives = [o for o in outcomes if o.kind not in NEGATIVE_KINDS]
    negatives = [o for o in outcomes if o.kind in NEGATIVE_KINDS]
    recall = sum(o.ok for o in positives) / len(positives) if positives else None
    reject = sum(o.ok for o in negatives) / len(negatives) if negatives else None
    return recall, reject


if __name__ == "__main__":
    main()
