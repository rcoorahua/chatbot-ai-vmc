"""Tiempo en un solo formato para todo el backend.

Los timestamps de DynamoDB son ISO-8601 UTC con milisegundos y sufijo `Z`
(`2026-08-27T10:00:00.000Z`): ancho fijo, asi que el orden lexicografico de la SK
`created_at#message_id` coincide con el cronologico (PLAN.md §4). Un formato distinto en un
solo sitio romperia ese orden sin que ningun test de unidad lo note.
"""

from datetime import UTC, datetime, timedelta


def utc_now() -> datetime:
    return datetime.now(UTC)


def to_iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def utc_now_iso() -> str:
    return to_iso(utc_now())


def epoch_seconds() -> int:
    return int(utc_now().timestamp())


def minutes_ago_iso(minutes: int) -> str:
    """Marca de tiempo de hace N minutos, en el mismo formato ISO que la SK de Messages.

    Sirve para acotar consultas por tiempo (ventana de contexto de la IA — D-004 — y rate
    limit — D-005) comparando strings, sin convertir cada item a datetime.
    """
    return to_iso(utc_now() - timedelta(minutes=minutes))
