"""Lectura de los golden sets (`tests/golden/*.jsonl`): una linea JSON por caso, `#` comenta."""

import json
from pathlib import Path

GOLDEN_DIR = Path(__file__).resolve().parent.parent / "golden"


def load_golden(name: str) -> list[dict]:
    lines = (GOLDEN_DIR / name).read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip() and not line.startswith("#")]
