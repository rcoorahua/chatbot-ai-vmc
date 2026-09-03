"""Recuperacion de conocimiento en Pinecone — RF-017 (FAQ desde contenido VMC), RF-018
(sin evidencia no se responde) y RF-019 (la fuente viaja con cada fragmento; el chip que
la muestra lo arma `agent/related.py`).

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
from dataclasses import dataclass, replace
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
    # Entro como evidencia por ser del mismo articulo que uno que supero el umbral, no por su
    # propio score (expansion por tema, ver `retrieve`). Solo informativo: AIUsage y la
    # consola lo marcan para poder juzgar la regla con datos.
    sibling: bool = False

    def as_context(self) -> str:
        """El fragmento tal como lo recibe el redactor: solo el texto.

        Hasta el 2026-09-03 la fuente viajaba pegada ("(Fuente: url)") para que el modelo la
        citara (RF-019). Ya no: el enlace sale como chip debajo de la respuesta desde
        `metadata.sources` (`agent/related.py`), determinista y sin gastar tokens en que el
        modelo copie una URL de tres lineas. Si el modelo escribe un enlace igual, el
        guardrail de salida solo deja pasar los que esten en la evidencia.
        """
        return self.text


# Timeout EXPLICITO por request a Pinecone, en segundos (DETAILS.md §4.18). El SDK ya trae un
# default de 30s (a diferencia del `None` de Gemini que colgo el worker 13 minutos, ver
# core/llm.py), pero 30s no deja margen: el peor caso de Gemini en un turno ya son 110s (2x15
# clasificar + 2x40 redactar, con respaldo) sobre un worker de 120s, y esta consulta puede
# llamarse DOS veces en el mismo turno (`_offer_handoff_form`/continuidad en ai_worker.py,
# rama "responde_al_bot"). Una busqueda vectorial normal responde en milisegundos; 10s ya es
# generoso y dispara mucho antes de comerse el presupuesto de la Lambda. Si Pinecone no
# responde a tiempo, `Index.search()` lanza `PineconeTimeoutError`, que `retrieve()` atrapa
# como cualquier otro fallo del proveedor (RF-018: sin evidencia -> handoff, nunca inventar).
_PINECONE_TIMEOUT_S = 10.0

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

        _index = Pinecone(
            api_key=settings.pinecone_api_key, timeout=_PINECONE_TIMEOUT_S
        ).Index(settings.pinecone_index_name)
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


@dataclass(frozen=True, slots=True)
class RagResult:
    """Todo lo que trajo el indice, separado por el umbral.

    `relevant` es la evidencia (lo unico que llega al redactor, RF-018). `discarded` son los
    hits que NO superaron el umbral: no son evidencia, pero la consola de dev los muestra para
    poder juzgar el retrieval cuando la respuesta cae en "sin evidencia" — sin esto, calibrar
    RAG_MIN_SCORE obliga a reproducir la consulta a mano con `helpcenter_upload --verify`.
    """

    relevant: list[Fragment]
    discarded: list[Fragment]
    threshold: float

    @property
    def all_fragments(self) -> list[Fragment]:
        """Relevantes primero (asi los recibe el redactor), descartados despues."""
        return self.relevant + self.discarded

    @property
    def siblings(self) -> list[Fragment]:
        """Los relevantes que entraron por expansion de tema y no por su score."""
        return [f for f in self.relevant if f.sibling]


# Cuantos hits de mas se piden al indice, ademas de `rag_top_k`, para tener de donde sacar
# hermanos: el fragmento con los pasos puede estar en el puesto 5 o 6 cuando una errata
# reordena la lista. Pinecone cobra por consulta, no por top_k, asi que pedir mas no cuesta.
_SIBLING_LOOKAHEAD = 4


def retrieve(
    question: str, *, top_k: int | None = None, min_score: float | None = None
) -> RagResult:
    """Busca en Pinecone y separa por el umbral. `relevant` vacio = sin evidencia.

    Los resultados por debajo de `rag_min_score` no cuentan como evidencia: Pinecone SIEMPRE
    devuelve los `top_k` mas cercanos, incluso para una pregunta que no tiene nada que ver con
    el Centro de Ayuda, asi que sin umbral el redactor creeria tener evidencia para cualquier
    cosa — que es justo lo que RF-018 prohibe.

    `min_score=0.0` desactiva el corte. Sirve para calibrarlo (ver los scores reales de una
    consulta); el pipeline nunca debe llamarlo asi. Nunca lanza (contrato del modulo).

    **Expansion por tema** (2026-09-03, patron "parent document / small-to-big" de los RAG:
    trozo chico para buscar, contexto del padre para redactar). El umbral decide UNA cosa: si
    hay evidencia. Cuando la hay, los fragmentos del MISMO articulo que quedaron hasta
    `rag_sibling_margin` por debajo entran tambien, hasta llenar `top_k`. Caso real: "hola
    como me regitro" (errata) puso sobre el umbral dos fragmentos del articulo de registro
    que hablaban de contraseña olvidada y de "si ya te registraste, inicia sesion", y dejo a
    0.006 por debajo justo el que tenia los pasos; el bot pregunto "¿ya tienes cuenta?". Un
    fragmento de OTRO articulo sigue fuera aunque este a un pelo: el tema no esta confirmado.
    """
    settings = get_settings()
    threshold = settings.rag_min_score if min_score is None else min_score
    text = (question or "").strip()
    if not text:
        return RagResult(relevant=[], discarded=[], threshold=threshold)

    limit = top_k or settings.rag_top_k
    margin = max(0.0, settings.rag_sibling_margin)
    search_k = limit + _SIBLING_LOOKAHEAD if margin > 0 else limit
    try:
        response = get_index().search(
            namespace=settings.pinecone_namespace,
            query={"inputs": {"text": text}, "top_k": search_k},
            fields=list(_FIELDS),
        )
    except Exception:  # noqa: BLE001 — cualquier fallo se trata como falta de evidencia
        logger.exception("Fallo la busqueda en Pinecone; se deriva por falta de evidencia")
        return RagResult(relevant=[], discarded=[], threshold=threshold)

    fragments = [fragment for hit in _hits(response) if (fragment := _to_fragment(hit))]
    # Los primeros `limit` se juzgan como siempre; los de mas alla son solo cantera de hermanos.
    head, tail = fragments[:limit], fragments[limit:]
    relevant = [f for f in head if f.score >= threshold]
    discarded = [f for f in head if f.score < threshold]
    if relevant and margin > 0:
        topics = {f.topic for f in relevant if f.topic}
        admitted = [
            f for f in discarded + tail
            if f.topic in topics and f.score >= threshold - margin
        ][: max(0, limit - len(relevant))]
        if admitted:
            relevant = relevant + [replace(f, sibling=True) for f in admitted]
            discarded = [f for f in discarded if f not in admitted]
    if fragments and not relevant:
        # Sin esto, calibrar el umbral obligaria a reproducir la consulta a mano.
        logger.info(
            "Sin evidencia sobre el umbral (%.2f); mejor score: %.3f",
            threshold,
            max(f.score for f in fragments),
        )
    return RagResult(relevant=relevant, discarded=discarded, threshold=threshold)


def search(
    question: str, *, top_k: int | None = None, min_score: float | None = None
) -> list[Fragment]:
    """Fragmentos relevantes para la pregunta, de mas a menos. Lista vacia = sin evidencia.

    Atajo sobre `retrieve()` para quien solo necesita la evidencia (scripts, calibracion);
    el pipeline usa `retrieve()` porque tambien registra lo descartado en AIUsage.
    """
    return retrieve(question, top_k=top_k, min_score=min_score).relevant


def as_context(fragments: list[Fragment]) -> list[str]:
    """Adapta los fragmentos a lo que espera `agent.writer.write_answer`."""
    return [fragment.as_context() for fragment in fragments]
