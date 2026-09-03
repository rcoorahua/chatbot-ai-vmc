"""Expansion por tema en la recuperacion (`rag.retrieve`, RAG_SIBLING_MARGIN) — RF-017/RF-018.

Patron "parent document / small-to-big": se busca por trozo chico y, confirmado el tema, se
le pasa al redactor el contexto de los hermanos. Caso real del 2026-09-03: "hola como me
regitro" (errata) dejo sobre el umbral dos fragmentos del articulo de registro que hablaban
de contraseña olvidada y de "si ya te registraste, inicia sesion" (0.846, 0.842), y a 0.006
por debajo justo la respuesta rapida con los pasos (0.834); el bot pregunto "¿ya tienes
cuenta?" en vez de explicar el registro.

Criterios:
  AC-S1  con al menos uno sobre el umbral, los del MISMO articulo dentro del margen entran
         como evidencia y quedan marcados `sibling`
  AC-S2  un fragmento de OTRO articulo no entra aunque este dentro del margen
  AC-S3  sin ninguno sobre el umbral no entra nada: RF-018 intacto
  AC-S4  fuera del margen no entra
  AC-S5  el redactor recibe como maximo `rag_top_k`: los hermanos llenan huecos, por score
  AC-S6  la cantera incluye los hits mas alla de `rag_top_k` (se piden `top_k + 4`)
  AC-S7  margen 0 apaga la expansion (y no se pide cantera)
  AC-S8  `all_fragments` no repite ni pierde fragmentos (consola de dev)

Doble del indice, sin Pinecone ni red.
"""

import pytest

from backend.agent import rag
from backend.core.config import reset_settings

REGISTRO = "¡Registrarte es fácil y rápido!"
COMISION = "La Comisión, ¿por qué, cuánto y cómo se paga?"


class FakeIndex:
    def __init__(self, hits):
        self._hits = hits
        self.calls = []

    def search(self, **kwargs):
        self.calls.append(kwargs)
        return {"result": {"hits": self._hits}}


def _hit(text, score, topic=REGISTRO):
    return {"_id": text, "_score": score, "fields": {
        "text": text, "topic": topic, "source_url": "https://ayuda.vmc.test/x"}}


@pytest.fixture
def indice(monkeypatch):
    def _install(hits, *, margin="0.04", top_k="4", threshold="0.84"):
        monkeypatch.setenv("RAG_SIBLING_MARGIN", margin)
        monkeypatch.setenv("RAG_TOP_K", top_k)
        monkeypatch.setenv("RAG_MIN_SCORE", threshold)
        reset_settings()
        index = FakeIndex(hits)
        monkeypatch.setattr(rag, "get_index", lambda: index)
        return index

    yield _install
    reset_settings()
    rag.reset_index()


# El caso real, tal como volvio del indice (mismo articulo los cuatro).
CASO_REAL = [
    _hit("He olvidado mi contraseña...", 0.846),
    _hit("El formulario me impide registrarme...", 0.842),
    _hit("Respuesta rápida: ingresa a vmcsubastas.com, Ingresar, Regístrate...", 0.834),
    _hit("¿Puedo registrarme como persona jurídica?", 0.826),
]


def test_los_hermanos_del_mismo_articulo_entran_como_evidencia(indice):
    indice(CASO_REAL)

    resultado = rag.retrieve("hola como me regitro")

    assert [f.score for f in resultado.relevant] == [0.846, 0.842, 0.834, 0.826]
    assert [f.sibling for f in resultado.relevant] == [False, False, True, True]
    assert resultado.discarded == []
    assert len(resultado.siblings) == 2
    # `search()` (evidencia para el redactor) tambien los trae.
    assert len(rag.search("hola como me regitro")) == 4


def test_otro_articulo_no_entra_aunque_este_cerca(indice):
    indice([
        _hit("registro, sobre el umbral", 0.85),
        _hit("comision, a un pelo", 0.835, topic=COMISION),
    ])

    resultado = rag.retrieve("como me registro")

    assert [f.text for f in resultado.relevant] == ["registro, sobre el umbral"]
    assert [f.text for f in resultado.discarded] == ["comision, a un pelo"]


def test_sin_nada_sobre_el_umbral_no_entra_nada(indice):
    """RF-018 intacto: la expansion necesita un tema CONFIRMADO. "¿cuanto esta el dolar hoy?"
    dio 0.835 en la calibracion y sigue siendo "sin evidencia"."""
    indice([_hit("algo", 0.835), _hit("otro", 0.83), _hit("mas", 0.82)])

    resultado = rag.retrieve("cuanto esta el dolar hoy")

    assert resultado.relevant == []
    assert len(resultado.discarded) == 3


def test_fuera_del_margen_no_entra(indice):
    indice([_hit("sobre el umbral", 0.85), _hit("mismo tema pero lejos", 0.79)])

    resultado = rag.retrieve("como me registro")

    assert [f.text for f in resultado.relevant] == ["sobre el umbral"]
    assert [f.text for f in resultado.discarded] == ["mismo tema pero lejos"]


def test_el_redactor_recibe_como_maximo_top_k(indice):
    """3 sobre el umbral + 3 hermanos con top_k=4: entra UN hermano, el de mayor score."""
    indice([
        _hit("a", 0.90), _hit("b", 0.88), _hit("c", 0.85),
        _hit("hermano 1", 0.835), _hit("hermano 2", 0.83), _hit("hermano 3", 0.82),
    ])

    resultado = rag.retrieve("como me registro")

    assert [f.text for f in resultado.relevant] == ["a", "b", "c", "hermano 1"]
    assert resultado.relevant[-1].sibling is True
    assert len(resultado.relevant) == 4


def test_la_cantera_llega_mas_alla_de_top_k(indice):
    """Con top_k=4, el hit numero 5 del mismo articulo entra si hay hueco: es lo que pasa
    cuando una errata reordena la lista y los pasos caen al quinto puesto."""
    index = indice([
        _hit("sobre el umbral", 0.85),
        _hit("comision 1", 0.838, topic=COMISION),
        _hit("comision 2", 0.837, topic=COMISION),
        _hit("comision 3", 0.836, topic=COMISION),
        _hit("los pasos, quinto puesto", 0.833),
    ])

    resultado = rag.retrieve("como me registro")

    assert index.calls[0]["query"]["top_k"] == 4 + rag._SIBLING_LOOKAHEAD
    assert [f.text for f in resultado.relevant] == ["sobre el umbral", "los pasos, quinto puesto"]
    assert resultado.relevant[1].sibling is True
    assert [f.text for f in resultado.discarded] == ["comision 1", "comision 2", "comision 3"]


def test_margen_cero_apaga_la_expansion(indice):
    index = indice(CASO_REAL, margin="0")

    resultado = rag.retrieve("hola como me regitro")

    assert index.calls[0]["query"]["top_k"] == 4, "sin expansion no se pide cantera"
    assert [f.score for f in resultado.relevant] == [0.846, 0.842]
    assert resultado.siblings == []


def test_all_fragments_no_repite_ni_pierde(indice):
    indice(CASO_REAL + [_hit("comision", 0.80, topic=COMISION)])

    resultado = rag.retrieve("hola como me regitro")

    textos = [f.text for f in resultado.all_fragments]
    assert len(textos) == len(set(textos))
    assert set(textos) == {h["fields"]["text"] for h in CASO_REAL}, (
        "la cantera no admitida (otro tema, mas alla de top_k) no se muestra: nunca se vio"
    )
