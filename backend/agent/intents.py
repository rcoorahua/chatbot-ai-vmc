"""Intenciones minimas del MVP (RF-016), en ingles como todo dato/estado del sistema (T7).

Es un `StrEnum` para que el valor se persista tal cual en `AIUsage.intent` y viaje sin
conversion a los prompts del clasificador y del redactor.
"""

from enum import StrEnum


class Intent(StrEnum):
    FAQ = "FAQ"
    CATALOG = "CATALOG"
    ADVISOR = "ADVISOR"
    OTHER = "OTHER"
