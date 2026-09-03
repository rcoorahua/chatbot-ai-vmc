"""Recuperacion en Pinecone — RF-017 / RF-018 / RF-019.

Criterios:
  AC-R1  la busqueda pide el namespace, el top_k y los campos que la ingesta guardo
  AC-R2  lo que no supera el umbral no cuenta como evidencia (RF-018)
  AC-R3  un fallo del proveedor se trata como falta de evidencia, no como excepcion
  AC-R4  el fragmento llega al redactor con su fuente (RF-019)

Se sustituye el indice por un doble en vez de simular el SDK: lo que hay que verificar es
nuestro contrato (parametros, umbral, normalizacion), no que `pinecone` funcione. Asi los
tests corren sin credenciales ni red.
"""

import pytest

from backend.agent import rag
from backend.core.config import reset_settings


class FakeIndex:
    """Doble del indice: registra como se lo consulto y devuelve una respuesta fija."""

    def __init__(self, hits=None, error=None):
        self._hits = hits or []
        self._error = error
        self.calls = []

    def search(self, **kwargs):
        self.calls.append(kwargs)
        if self._error:
            raise self._error
        return {"result": {"hits": self._hits}}


def _hit(text, score, topic="Comision", url="https://ayuda.vmc.test/comision"):
    """Forma que devuelve un indice con embedding integrado."""
    return {"_id": "hc-1", "_score": score, "fields": {
        "text": text, "topic": topic, "source_url": url}}


@pytest.fixture
def fake_index(monkeypatch):
    def _install(**kwargs):
        index = FakeIndex(**kwargs)
        monkeypatch.setattr(rag, "get_index", lambda: index)
        return index

    yield _install
    rag.reset_index()


# ───────────────────────── AC-R1: como se consulta el indice ─────────────────────────


def test_la_busqueda_usa_namespace_top_k_y_campos(fake_index):
    index = fake_index(hits=[_hit("La comision minima es 50 SubasCoins.", 0.9)])

    rag.search("cuanto es la comision")

    call = index.calls[0]
    assert call["namespace"] == "helpcenter"
    # top_k + 4 de cantera para la expansion por tema (RAG_SIBLING_MARGIN > 0); al redactor le
    # siguen llegando como maximo `rag_top_k` (4). Ver tests/test_agent_rag_siblings.py.
    assert call["query"] == {"inputs": {"text": "cuanto es la comision"}, "top_k": 8}
    assert set(call["fields"]) == {"text", "topic", "source_url"}, (
        "si falta un campo, el fragmento llega sin fuente y RF-019 no se puede cumplir"
    )


def test_el_top_k_se_puede_acotar_por_llamada(fake_index):
    index = fake_index(hits=[])

    rag.search("una pregunta", top_k=2)

    assert index.calls[0]["query"]["top_k"] == 2 + rag._SIBLING_LOOKAHEAD


@pytest.mark.parametrize("question", ["", "   ", None])
def test_pregunta_vacia_no_consulta(fake_index, question):
    index = fake_index(hits=[_hit("texto", 0.9)])

    assert rag.search(question) == []
    assert index.calls == []


# ───────────────────────── AC-R2: el umbral es RF-018 ─────────────────────────


def test_lo_que_no_supera_el_umbral_no_es_evidencia(fake_index, monkeypatch):
    # Pinecone siempre devuelve los top_k mas cercanos: sin umbral, una pregunta ajena al
    # Centro de Ayuda parece tener evidencia y el bot inventaria una respuesta.
    monkeypatch.setenv("RAG_MIN_SCORE", "0.75")
    reset_settings()
    index_hits = [_hit("algo poco relacionado", 0.42), _hit("nada que ver", 0.31)]
    fake_index(hits=index_hits)
    try:
        assert rag.search("como cambio la llanta de mi carro") == []
    finally:
        reset_settings()


def test_lo_que_supera_el_umbral_se_devuelve_ordenado(fake_index, monkeypatch):
    monkeypatch.setenv("RAG_MIN_SCORE", "0.5")
    reset_settings()
    fake_index(hits=[_hit("mejor", 0.91), _hit("peor", 0.55), _hit("descartado", 0.20)])
    try:
        fragments = rag.search("cuanto es la comision")
    finally:
        reset_settings()

    assert [f.text for f in fragments] == ["mejor", "peor"]
    assert fragments[0].score == pytest.approx(0.91)


def test_retrieve_separa_lo_relevante_de_lo_descartado(fake_index, monkeypatch):
    """El pipeline registra TODO lo que trajo el indice (consola de dev), pero solo lo que
    supera el umbral cuenta como evidencia."""
    monkeypatch.setenv("RAG_MIN_SCORE", "0.5")
    reset_settings()
    fake_index(hits=[_hit("mejor", 0.91), _hit("bajo el umbral", 0.20)])
    try:
        resultado = rag.retrieve("cuanto es la comision")
    finally:
        reset_settings()

    assert [f.text for f in resultado.relevant] == ["mejor"]
    assert [f.text for f in resultado.discarded] == ["bajo el umbral"]
    assert resultado.threshold == pytest.approx(0.5)
    assert [f.text for f in resultado.all_fragments] == ["mejor", "bajo el umbral"]


def test_un_fallo_del_proveedor_tampoco_rompe_retrieve(fake_index):
    fake_index(error=RuntimeError("Pinecone no responde"))

    resultado = rag.retrieve("cuanto es la comision")

    assert resultado.relevant == [] and resultado.discarded == []


def test_el_umbral_se_puede_desactivar_para_calibrar(fake_index, monkeypatch):
    monkeypatch.setenv("RAG_MIN_SCORE", "0.9")
    reset_settings()
    fake_index(hits=[_hit("bajo", 0.2)])
    try:
        assert len(rag.search("x", min_score=0.0)) == 1
    finally:
        reset_settings()


# ───────────────────────── AC-R3: nunca lanza ─────────────────────────


def test_un_fallo_del_proveedor_se_trata_como_falta_de_evidencia(fake_index):
    fake_index(error=RuntimeError("Pinecone no responde"))

    # Devolver [] lleva a handoff (RF-018). Propagar la excepcion dejaria el mensaje sin
    # respuesta y sin asesor.
    assert rag.search("cuanto es la comision") == []


def test_un_hit_sin_texto_se_ignora(fake_index):
    fake_index(hits=[{"_id": "x", "_score": 0.99, "fields": {"text": "   "}}, _hit("bueno", 0.99)])

    assert [f.text for f in rag.search("x")] == ["bueno"]


def test_acepta_la_forma_clasica_de_la_api_de_vectores(monkeypatch):
    # Si el indice se recreara sin embedding integrado, la respuesta trae `matches`/`metadata`.
    class ClassicIndex(FakeIndex):
        def search(self, **kwargs):
            self.calls.append(kwargs)
            return {"matches": [{"id": "hc-1", "score": 0.88, "metadata": {
                "text": "texto clasico", "topic": "T", "source_url": "u"}}]}

    monkeypatch.setattr(rag, "get_index", lambda: ClassicIndex())

    assert [f.text for f in rag.search("x", min_score=0.0)] == ["texto clasico"]


# ───────────────────────── AC-R4: el fragmento lleva su fuente ─────────────────────────


def test_el_contexto_incluye_la_fuente(fake_index):
    fake_index(hits=[_hit("La comision minima es 50 SubasCoins.", 0.95)])

    contexto = rag.as_context(rag.search("cuanto es la comision"))

    assert contexto == [
        "La comision minima es 50 SubasCoins.\n(Fuente: https://ayuda.vmc.test/comision)"
    ]


def test_sin_fuente_el_contexto_es_solo_el_texto():
    assert rag.Fragment(text="solo texto").as_context() == "solo texto"


def test_sin_credencial_pedir_el_indice_falla_claro(monkeypatch):
    monkeypatch.setenv("PINECONE_API_KEY", "")
    reset_settings()
    rag.reset_index()
    try:
        with pytest.raises(RuntimeError, match="PINECONE_API_KEY"):
            rag.get_index()
    finally:
        reset_settings()
        rag.reset_index()
