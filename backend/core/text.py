"""Normalizacion de texto compartida por reglas, lexicos y comparaciones.

Vive en `core` porque la necesitan tanto las integraciones (`agent/heuristics`, `flows`,
`trivial`, `guardrails`, `followups`, `related`) como el dominio (`tickets/taxonomy`), y la
regla de dependencias (backend/__init__.py) prohibe que el dominio importe una integracion:
antes cada uno llevaba su copia identica de `normalize` (auditoria 2026-09-06).

Un lexico se escribe en español natural (con tildes) y pasa por la MISMA funcion que el
mensaje del usuario, de modo que "pásame", "pasame" y "PASAME" caen en la misma entrada sin
duplicarla a mano.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

_WHITESPACE = re.compile(r"\s+")

# Signos que no cambian lo que se dijo: "¡¿ok?!" y "(ok)" son "ok". UN solo conjunto para
# acuses, triviales y si/no de flujos — antes habia dos distintos y "(ok)" era acuse en un
# sitio y no en otro.
BARE_PUNCTUATION = "!¡?¿.,;:() "

# Categorias Unicode que se descartan al mirar como TERMINA un texto: simbolos (los emoji son
# `So`), modificadores de simbolo (tonos de piel), marcas sin espaciado (selectores de
# variacion), invisibles de formato (el ZWJ que une emoji compuestos) y espacios.
TRAILING_DECORATION = frozenset({"So", "Sk", "Sm", "Mn", "Cf", "Zs"})


def strip_accents(text: str) -> str:
    """NFKD separa cada letra acentuada en letra base mas marca combinante; descartar las
    marcas deja el texto sin acentos. La eñe tambien pierde su marca ("piña" -> "pina"):
    aceptable porque el lexico pasa por la misma funcion y ninguna entrada colisiona."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize(text: str | None) -> str:
    """Minusculas, sin tildes ni diereses, espacios comprimidos. `None` es ""."""
    return _WHITESPACE.sub(" ", strip_accents((text or "").lower().strip()))


def bare(text: str | None) -> str:
    """`normalize` y sin la puntuacion de los bordes: la forma en que se compara un acuse o
    un saludo suelto contra su lexico."""
    return normalize(text).strip(BARE_PUNCTUATION)


def phrases(*items: str) -> tuple[str, ...]:
    """Lexico ordenado (para `startswith`/`in` con precedencia), ya normalizado."""
    return tuple(normalize(item) for item in items)


def lexicon(*items: str) -> frozenset[str]:
    """Lexico de pertenencia exacta (`in`), ya normalizado."""
    return frozenset(normalize(item) for item in items)


def strip_trailing_decoration(
    text: str | None, *, extra: Iterable[str] = (), keep: str = ""
) -> str:
    """Quita del FINAL los emoji, espacios y demas decoracion (D-025 permite un emoji de
    cierre), para poder mirar el signo real con el que termina un mensaje. `extra` suma
    categorias (p. ej. "Po", puntuacion) y `keep` protege caracteres que si importan ("?")."""
    categories = TRAILING_DECORATION | frozenset(extra)
    result = (text or "").rstrip()
    while result and result[-1] not in keep and unicodedata.category(result[-1]) in categories:
        result = result[:-1].rstrip()
    return result
