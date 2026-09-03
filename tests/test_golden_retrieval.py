"""Golden set de recuperacion (tests/golden/retrieval.jsonl) — parte OFFLINE. RF-017/018, RB-009.

Aqui solo se valida la FORMA del golden set: que cada caso tenga lo que el benchmark necesita
y que la muestra cubra lo que promete BENCHMARK.md (los 22 articulos, erratas, cortas y
negativos). La medicion real corre a mano contra Pinecone:
`python -m scripts.eval_retrieval` (una consulta por caso, sin Gemini; por eso no esta en CI).
"""

import json
from collections import Counter
from pathlib import Path

GOLDEN = Path(__file__).parent / "golden" / "retrieval.jsonl"

POSITIVE_KINDS = frozenset({"parafrasis", "errata", "corta", "canonica"})
NEGATIVE_KINDS = frozenset({"sin_respuesta", "ajena"})
KINDS = POSITIVE_KINDS | NEGATIVE_KINDS

# Lo que BENCHMARK.md dice que cubre la muestra. Si el corpus crece, subir estos numeros.
MIN_ARTICLES = 22
MIN_PER_KIND = {"parafrasis": 60, "errata": 8, "corta": 6, "canonica": 5,
                "sin_respuesta": 6, "ajena": 10}


def load_golden() -> list[dict]:
    lines = GOLDEN.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip() and not line.startswith("#")]


CASES = load_golden()


def test_cada_caso_tiene_la_forma_que_el_benchmark_necesita():
    for case in CASES:
        assert set(case) == {"query", "kind", "topics", "note"}, case
        assert case["query"].strip() and case["note"].strip(), case
        assert case["kind"] in KINDS, case
        assert isinstance(case["topics"], list), case
        if case["kind"] in NEGATIVE_KINDS:
            assert case["topics"] == [], f"un negativo no espera articulo: {case}"
        else:
            assert case["topics"], f"un positivo necesita al menos un articulo: {case}"
            assert len(case["topics"]) == len(set(case["topics"])), case


def test_no_hay_consultas_repetidas():
    queries = [c["query"].strip().lower() for c in CASES]
    duplicated = [q for q, n in Counter(queries).items() if n > 1]
    assert not duplicated, duplicated


def test_la_muestra_cubre_lo_que_promete_benchmark_md():
    by_kind = Counter(c["kind"] for c in CASES)
    for kind, minimum in MIN_PER_KIND.items():
        assert by_kind[kind] >= minimum, f"{kind}: {by_kind[kind]} < {minimum}"
    # Cada articulo del Centro de Ayuda tiene al menos dos parafrasis: con una sola, un
    # articulo que "pasa" no dice nada de si el embedding lo entiende o si acerto de suerte.
    per_article: Counter[str] = Counter()
    for case in CASES:
        if case["kind"] == "parafrasis":
            per_article[case["topics"][0]] += 1
    assert len(per_article) >= MIN_ARTICLES, sorted(per_article)
    thin = [t for t, n in per_article.items() if n < 2]
    assert not thin, f"articulos con una sola parafrasis: {thin}"


def test_las_consultas_no_copian_el_titulo_del_articulo():
    """Una parafrasis que ES el titulo mide el caso facil, no al usuario real."""
    for case in CASES:
        if case["kind"] != "parafrasis":
            continue
        titles = {t.strip("¡!¿?. ").lower() for t in case["topics"]}
        assert case["query"].strip("¡!¿?. ").lower() not in titles, case
