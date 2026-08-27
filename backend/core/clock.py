"""Tiempo en un solo formato para todo el backend.

Los timestamps de DynamoDB son ISO-8601 UTC con milisegundos y sufijo `Z`
(`2026-08-27T10:00:00.000Z`): ancho fijo, asi que el orden lexicografico de la SK
`created_at#message_id` coincide con el cronologico (PLAN.md §4). Un formato distinto en un
solo sitio romperia ese orden sin que ningun test de unidad lo note.
"""

from datetime import UTC, datetime


def utc_now() -> datetime:
    return datetime.now(UTC)


def to_iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def utc_now_iso() -> str:
    return to_iso(utc_now())


def epoch_seconds() -> int:
    return int(utc_now().timestamp())
