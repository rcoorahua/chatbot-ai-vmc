"""Recuperacion de conocimiento en Pinecone — RF-017 (FAQ desde contenido VMC), RF-018
(sin evidencia no se responde) y RF-019 (incluir la fuente cuando existe).

El indice usa **embedding integrado** (`multilingual-e5-large` dentro de Pinecone), no un
modelo de embeddings nuestro. Tres consecuencias que justifican la eleccion:

- La ingesta y la consulta embeben con el MISMO modelo por construccion. Desalinearlos —subir
  con un modelo y consultar con otro— es el error clasico del RAG y no da error, solo
  resultados malos.
- No hay que versionar dimensiones ni re-embeber todo al cambiar de proveedor de LLM: Gemini
  (o Haiku) redacta, pero no embebe.
- La busqueda viaja como texto (`query.inputs.text`), asi que este modulo no necesita el SDK
  de ningun modelo, solo el de Pinecone.

Contrato con quien llama (el pipeline de `workers/ai_worker.py`): `search()` **nunca lanza**.
Una lista vacia significa "no hay evidencia" y, por RF-018, eso es handoff — jamas completar
con conocimiento general. Un fallo del proveedor cae en el mismo camino a proposito: preferimos
derivar a un humano antes que arriesgar una respuesta inventada por una caida de Pinecone.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from backend.core.config import get_settings

logger = logging.getLogger(__name__)

# Campos que la ingesta guarda en cada registro (scripts/helpcenter_fetch.py). Se piden
# explicitamente porque el indice devuelve solo lo que se le nombra.
_FIELDS = ("text", "topic", "source_url")


@dataclass(frozen=True, slots=True)
class Fragment:
    """Un trozo de conocimiento recuperado, con su procedencia."""

    text: str
    topic: str = ""
    source_url: str = ""
    score: float = 0.0

    def as_context(self) -> str:
        """El fragmento tal como lo recibe el redactor.

        La fuente viaja PEGADA al texto en vez de en un campo aparte para que el modelo pueda
        citarla en la respuesta (RF-019) sin que el prompt tenga que explicar una estructura.
        """
        if not self.source_url:
            return self.text
        return f"{self.text}\n(Fuente: {self.source_url})"


_index: Any | None = None


def get_index() -> Any:
    """Indice de Pinecone, memorizado por proceso (se reusa entre invocaciones de la Lambda)."""
    global _index
    if _index is None:
        settings = get_settings()
        if not settings.pinecone_api_key:
            raise RuntimeError(
                "Falta PINECONE_API_KEY (en AWS se lee de Secrets Manager, no del entorno en claro)"
            )
        from pinecone import Pinecone

        _index = Pinecone(api_key=settings.pinecone_api_key).Index(settings.pinecone_index_name)
    return _index


def reset_index() -> None:
    """Limpia el indice memorizado. Para tests y rotacion de credenciales."""
    global _index
    _index = None


def _field(source: Any, name: str, default: Any = None) -> Any:
    """Lee un campo de la respuesta de Pinecone, venga como dict o como objeto.

    El SDK ha devuelto ambas formas segun la version y el tipo de indice; normalizar aqui evita
    que un `upgrade` del cliente rompa el pipeline entero.
    """
    if source is None:
        return default
    if isinstance(source, dict):
        return source.get(name, default)
    return getattr(source, name, default)


def _hits(response: Any) -> list[Any]:
    result = _field(response, "result")
    hits = _field(result, "hits")
    if hits is None:
        # Forma de la API de vectores clasica; se acepta para que el mismo codigo sirva si el
        # indice se recrea sin embedding integrado.
        hits = _field(response, "matches")
    return list(hits or [])


def _to_fragment(hit: Any) -> Fragment | None:
    fields = _field(hit, "fields") or _field(hit, "metadata") or {}
    text = (_field(fields, "text") or "").strip()
    if not text:
        return None
    score = _field(hit, "_score")
    if score is None:
        score = _field(hit, "score", 0.0)
    return Fragment(
        text=text,
        topic=_field(fields, "topic") or "",
        source_url=_field(fields, "source_url") or "",
        score=float(score or 0.0),
    )


def search(
    question: str, *, top_k: int | None = None, min_score: float | None = None
) -> list[Fragment]:
    """Fragmentos relevantes para la pregunta, de mas a menos. Lista vacia = sin evidencia.

    Los resultados por debajo de `rag_min_score` se descartan: Pinecone SIEMPRE devuelve los
    `top_k` mas cercanos, incluso para una pregunta que no tiene nada que ver con el Centro de
    Ayuda, asi que sin umbral el redactor creeria tener evidencia para cualquier cosa — que es
    justo lo que RF-018 prohibe.

    `min_score=0.0` desactiva el corte. Sirve para calibrarlo (ver los scores reales de una
    consulta); el pipeline nunca debe llamarlo asi.
    """
    text = (question or "").strip()
    if not text:
        return []

    settings = get_settings()
    limit = top_k or settings.rag_top_k
    threshold = settings.rag_min_score if min_score is None else min_score
    try:
        response = get_index().search(
            namespace=settings.pinecone_namespace,
            query={"inputs": {"text": text}, "top_k": limit},
            fields=list(_FIELDS),
        )
    except Exception:  # noqa: BLE001 — cualquier fallo se trata como falta de evidencia
        logger.exception("Fallo la busqueda en Pinecone; se deriva por falta de evidencia")
        return []

    fragments = [fragment for hit in _hits(response) if (fragment := _to_fragment(hit))]
    relevant = [f for f in fragments if f.score >= threshold]
    if fragments and not relevant:
        # Sin esto, calibrar el umbral obligaria a reproducir la consulta a mano.
        logger.info(
            "Sin evidencia sobre el umbral (%.2f); mejor score: %.3f",
            threshold,
            max(f.score for f in fragments),
        )
    return relevant


def as_context(fragments: list[Fragment]) -> list[str]:
    """Adapta los fragmentos a lo que espera `agent.writer.write_answer`."""
    return [fragment.as_context() for fragment in fragments]
