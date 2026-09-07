"""Dobles del modelo y del indice. Sin red, sin credenciales.

Se sustituye `LLMClient` por un doble en vez de simular el SDK de Google, y el indice de
Pinecone por un `FakeIndex` (nivel unidad) o un `retrieve` parcheado (nivel worker): lo que
hay que verificar es NUESTRO contrato (tier, tope de tokens, parseo, umbral, fallbacks), no
que `google-genai` o `pinecone` funcionen.
"""

from typing import Any

from backend.agent.rag import Fragment, RagResult
from backend.core import llm
from backend.core.llm import LLMClient, LLMResponse

USAGE = {"input": 100, "output": 10, "cached_read": 0, "cached_creation": 0}
THRESHOLD = 0.84
NO_MODEL_ALLOWED = "este camino no debe llamar a ningun modelo"
NO_RAG_ALLOWED = "este camino no debe llamar al RAG"


class FakeLLM(LLMClient):
    """Doble programable del cliente: registra cada llamada y responde por tier.

    - FAST (clasificador): `<intent>{intent}</intent>`.
    - ANSWER (redactor): la siguiente de `answers` si hay cola (continuidad paso a paso), si no
      `answer` fija.
    - `text` fuerza el mismo texto para cualquier tier (tests de parseo del clasificador).
    - `error` hace que cada llamada lo lance (Gemini caido, cuota agotada).
    """

    provider = "fake"

    def __init__(
        self,
        *,
        intent: str = "FAQ",
        answer: str = "Respuesta con evidencia.",
        answers: list[str] | None = None,
        text: str | None = None,
        usage: dict[str, int] | None = None,
        error: Exception | None = None,
        latency_ms: int = 50,
    ) -> None:
        self.intent = intent
        self.answer = answer
        self.answers = list(answers or [])
        self.text = text
        self.usage = usage or dict(USAGE)
        self.error = error
        self.latency_ms = latency_ms
        self.calls: list[dict[str, Any]] = []

    def generate(self, *, tier, system, messages, max_output_tokens, temperature=None):
        self.calls.append(
            {
                "tier": tier,
                "system": system,
                "messages": messages,
                "max_output_tokens": max_output_tokens,
                "temperature": temperature,
            }
        )
        if self.error is not None:
            raise self.error
        if self.text is not None:
            text = self.text
        elif tier == llm.ModelTier.FAST:
            text = f"<intent>{self.intent}</intent>"
        elif self.answers:
            text = self.answers.pop(0)
        else:
            text = self.answer
        return LLMResponse(
            text=text,
            model=llm.model_for(tier).name,
            tier=tier,
            usage=self.usage,
            latency_ms=self.latency_ms,
        )

    def answer_calls(self) -> list[dict[str, Any]]:
        return [c for c in self.calls if c["tier"] == llm.ModelTier.ANSWER]

    def classify_calls(self) -> list[dict[str, Any]]:
        return [c for c in self.calls if c["tier"] == llm.ModelTier.FAST]

    def tiers(self) -> list[llm.ModelTier]:
        return [c["tier"] for c in self.calls]


class ExplodingLLM(LLMClient):
    """Para caminos que NO deben tocar un modelo (triviales, reglas, botones): si se llama,
    el test falla por si mismo."""

    provider = "fake"

    def generate(self, **kwargs):
        raise AssertionError(NO_MODEL_ALLOWED)


def install_llm(monkeypatch, client: LLMClient) -> LLMClient:
    """Instala el doble en los tres puntos por donde el backend pide el cliente."""
    for target in (
        "backend.core.llm.get_client",
        "backend.agent.classifier.get_client",
        "backend.agent.writer.get_client",
    ):
        monkeypatch.setattr(target, lambda: client)
    return client


# ───────────────────────────── RAG a nivel worker: `rag.retrieve` ─────────────────────────────


def fragmento(
    text: str = "La comision es el 3.9%.",
    *,
    topic: str = "Comision",
    score: float = 0.9,
    source_url: str | None = "https://centro-de-ayuda-vmc.vercel.app/comision",
    sibling: bool = False,
) -> Fragment:
    return Fragment(text=text, topic=topic, score=score, source_url=source_url, sibling=sibling)


def con_evidencia(*fragments: Fragment, threshold: float = THRESHOLD) -> RagResult:
    return RagResult(relevant=list(fragments), discarded=[], threshold=threshold)


def sin_evidencia(*discarded: Fragment, threshold: float = THRESHOLD) -> RagResult:
    """Hubo hits pero bajo el umbral: no es evidencia (RF-018) y aun asi queda registrado."""
    return RagResult(relevant=[], discarded=list(discarded), threshold=threshold)


class RagSpy:
    """`rag.retrieve` de mentira que registra QUE se le pregunto — es lo que cambian la
    continuidad (TD-009), los flujos (consulta canonica) y las hermanas (D-030)."""

    def __init__(self, respond) -> None:
        self.queries: list[str] = []
        self._respond = respond

    def __call__(self, text: str, **kwargs) -> RagResult:
        self.queries.append(text)
        return self._respond(text) if callable(self._respond) else self._respond


def install_rag(monkeypatch, retrieve) -> Any:
    """Parchea `rag.retrieve` (el que usa el worker). `retrieve` puede ser un RagResult fijo,
    una funcion `text -> RagResult` o un RagSpy."""
    doble = retrieve if callable(retrieve) else RagSpy(retrieve)
    monkeypatch.setattr("backend.agent.rag.retrieve", doble)
    return doble


def rag_prohibido(monkeypatch) -> None:
    """Para pasos donde el RAG NO debe tocarse (ofrecer botones, D-028)."""

    def _boom(*args, **kwargs):
        raise AssertionError(NO_RAG_ALLOWED)

    monkeypatch.setattr("backend.agent.rag.retrieve", _boom)


# ───────────────────── Pinecone a nivel unidad: `rag.get_index` ─────────────────────


class FakeIndex:
    """Doble del indice de Pinecone: registra como se lo consulto y devuelve hits fijos."""

    def __init__(self, hits: list[dict] | None = None, error: Exception | None = None) -> None:
        self._hits = hits or []
        self._error = error
        self.calls: list[dict] = []

    def search(self, **kwargs):
        self.calls.append(kwargs)
        if self._error:
            raise self._error
        return {"result": {"hits": self._hits}}


def hit(
    text: str,
    score: float,
    *,
    topic: str = "Comision",
    url: str = "https://ayuda.vmc.test/comision",
    id: str | None = None,
) -> dict:
    """Forma que devuelve un indice con embedding integrado (`fields` + `_score`)."""
    return {
        "_id": id or text,
        "_score": score,
        "fields": {"text": text, "topic": topic, "source_url": url},
    }
