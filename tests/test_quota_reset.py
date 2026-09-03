"""`quota.seconds_until_daily_reset` — DETAILS.md §4.9 (hallazgo de code-review sobre PR #125).

La ventana de `take_daily_slot` es un dia CALENDARIO UTC (`D#2026-09-01`), no una hora rodante
desde el bloqueo: un `Retry-After` fijo (antes "3600") mentia en los dos sentidos. Prueba pura,
sin DynamoDB: solo aritmetica de fechas.
"""

from datetime import UTC, datetime

from backend.agent import quota


def test_a_un_segundo_de_medianoche_el_reset_es_casi_instantaneo(monkeypatch):
    monkeypatch.setattr(quota, "utc_now", lambda: datetime(2026, 9, 3, 23, 59, 59, tzinfo=UTC))
    assert quota.seconds_until_daily_reset() == 1


def test_justo_despues_de_medianoche_el_reset_es_de_casi_un_dia(monkeypatch):
    monkeypatch.setattr(quota, "utc_now", lambda: datetime(2026, 9, 3, 0, 0, 1, tzinfo=UTC))
    assert quota.seconds_until_daily_reset() == 24 * 3600 - 1


def test_a_medio_dia_faltan_doce_horas(monkeypatch):
    monkeypatch.setattr(quota, "utc_now", lambda: datetime(2026, 9, 3, 12, 0, 0, tzinfo=UTC))
    assert quota.seconds_until_daily_reset() == 12 * 3600
