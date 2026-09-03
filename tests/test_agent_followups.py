"""Continuidad conversacional para la consulta al RAG (`agent/followups.py`) — RF-017/RF-018.

Criterios (puros, sin Pinecone ni modelos):
  AC-S1  un acuse ("ya estoy ahí", "listo") o un pedido de seguir ("y luego") es continuación
  AC-S2  un mensaje corto solo es continuación si el bot acababa de preguntar algo: una
         pregunta corta que se sostiene sola NO debe arrastrar el tema anterior
  AC-S3  la consulta se arma con la pregunta previa del USUARIO, no con la respuesta del bot
  AC-S4  sin pregunta previa, o si no es continuación, la consulta queda tal cual (el
         comportamiento de siempre)
  AC-S5  la pregunta previa se busca saltando otras continuaciones, y no más allá de la
         ventana: un tema de hace rato no se arrastra

El caso de la conversación real que motivó el módulo está verificado aparte contra el índice
de Pinecone: "Ya estoy ahi" pasaba de 0/4 fragmentos sobre el umbral (mejor 0.789) a 4/4
(mejor 0.874) al contextualizar.
"""

import pytest

from backend.agent import followups

PREGUNTA = "¿Cómo me registro en VMC?"
BOT_PREGUNTA = "El primer paso es ingresar a vmcsubastas.com. ¿Me avisas cuando estés ahí?"
BOT_AFIRMA = "La comisión es del 3.9% sobre el valor de la oferta."


# ───────────────────────── AC-S1: acuses y pedidos de seguir ─────────────────────────


@pytest.mark.parametrize(
    "texto",
    ["Ya estoy ahi", "ya estoy ahí", "Listo", "hecho", "ok", "Sí", "dale", "ya", "entendido"],
)
def test_un_acuse_es_continuacion(texto):
    continuacion, regla = followups.is_continuation(texto)
    assert continuacion is True and regla == "acuse"


@pytest.mark.parametrize(
    "texto", ["y luego?", "¿y después?", "que sigue", "siguiente paso", "continua", "y que mas"]
)
def test_pedir_seguir_es_continuacion(texto):
    continuacion, regla = followups.is_continuation(texto)
    assert continuacion is True and regla == "pide_seguir"


# ───────────────────────── AC-S2: lo corto no basta ─────────────────────────


@pytest.mark.parametrize(
    "texto",
    [
        "¿cuánto es la comisión?",
        "quiero un asesor",
        "cómo consigno",
        "que es subascoins",
    ],
)
def test_una_pregunta_corta_que_se_sostiene_sola_no_es_continuacion(texto):
    """Sin esto, cualquier mensaje breve arrastraria el tema anterior y la consulta al indice
    mezclaria dos preguntas distintas."""
    assert followups.is_continuation(texto)[0] is False


def test_lo_corto_si_es_continuacion_cuando_el_bot_acababa_de_preguntar():
    assert followups.is_continuation("en la web", bot_asked=False)[0] is False
    continuacion, regla = followups.is_continuation("en la web", bot_asked=True)
    assert continuacion is True and regla == "responde_al_bot"


def test_un_mensaje_largo_nunca_es_continuacion():
    largo = (
        "ya estoy ahí pero me sale un error cuando pongo mi documento y no sé si es por el "
        "navegador o por mi conexión"
    )
    assert followups.is_continuation(largo, bot_asked=True)[0] is False


def test_solo_cuenta_la_pregunta_con_la_que_el_bot_cierra():
    assert followups.bot_asked_something(BOT_PREGUNTA) is True
    assert followups.bot_asked_something(BOT_AFIRMA) is False
    assert followups.bot_asked_something(None) is False


@pytest.mark.parametrize(
    "mensaje",
    [
        "¿Deseas que te explique el siguiente paso? 🚚",
        "¿En qué te ayudo? 😊",
        "¿Quieres que te conecte con un asesor del equipo? 🙏  ",
    ],
)
def test_el_emoji_final_no_esconde_la_pregunta(mensaje):
    """D-025 permite UN emoji al cierre, así que casi toda pregunta real del bot llega con uno
    detrás del signo. Mirando solo el último carácter, esta regla no se activaba nunca — se vio
    en una conversación real el 2026-09-02."""
    assert followups.bot_asked_something(mensaje) is True


@pytest.mark.parametrize(
    "mensaje",
    [
        "La comisión es del 3.9% sobre el valor de la oferta.",
        "Listo, lo dejamos ahí 🙂",
        "Tu saldo se devuelve en 5 días 💰",
    ],
)
def test_quitar_el_emoji_no_convierte_una_afirmacion_en_pregunta(mensaje):
    """Solo se descarta decoración: si debajo del emoji hay un punto o una cifra, sigue sin
    ser una pregunta y el turno del usuario no depende de ella."""
    assert followups.bot_asked_something(mensaje) is False


def test_la_respuesta_corta_a_una_pregunta_con_emoji_si_se_contextualiza():
    """El caso que quedaba fuera: contestar algo corto que NO es un "sí" ni un "listo"."""
    consulta = followups.build_query(
        "en la web",
        previous_question="Hola como me registro",
        last_bot_message=(
            "El primer paso es ingresar. ¿Deseas que te explique el siguiente paso? 🚚"
        ),
    )
    assert consulta.contextualized is True and consulta.rule == "responde_al_bot"
    assert consulta.text == "Hola como me registro"


# ───────────────────────── AC-S3 y AC-S4: la consulta que se arma ─────────────────────────


def test_la_continuacion_se_busca_con_la_pregunta_previa_sola():
    """Sin pegarle el texto del seguimiento: medido contra el índice real, "¿Cómo me
    registro?" recupera 4/4 fragmentos y "¿Cómo me registro? sí" solo 1/4 — las palabras de un
    acuse no describen nada del corpus y dispersan el embedding."""
    consulta = followups.build_query(
        "Ya estoy ahi", previous_question=PREGUNTA, last_bot_message=BOT_PREGUNTA
    )
    assert consulta.contextualized is True and consulta.rule == "acuse"
    assert consulta.text == PREGUNTA


def test_la_respuesta_del_bot_no_entra_en_la_consulta():
    """El texto del bot está redactado CON el corpus: meterlo acercaría la consulta a los
    fragmentos ya usados en vez de a los que faltan."""
    consulta = followups.build_query(
        "Ya estoy ahi", previous_question=PREGUNTA, last_bot_message=BOT_PREGUNTA
    )
    assert "vmcsubastas.com" not in consulta.text


def test_sin_pregunta_previa_la_consulta_no_cambia():
    consulta = followups.build_query("Ya estoy ahi", previous_question=None)
    assert consulta.contextualized is False and consulta.text == "Ya estoy ahi"


def test_una_pregunta_completa_se_busca_tal_cual():
    consulta = followups.build_query(
        "¿cuánto es la comisión?", previous_question=PREGUNTA, last_bot_message=BOT_PREGUNTA
    )
    assert consulta.contextualized is False
    assert consulta.text == "¿cuánto es la comisión?"


def test_la_consulta_tiene_tope():
    consulta = followups.build_query(
        "listo", previous_question="a" * 500, last_bot_message=BOT_PREGUNTA
    )
    assert len(consulta.text) == followups.MAX_QUERY_CHARS


# ───────────────────────── AC-S5: de dónde sale la pregunta previa ─────────────────────────


def test_la_pregunta_previa_salta_otras_continuaciones():
    historial = [PREGUNTA, "ok", "listo"]
    assert followups.last_user_question(historial) == PREGUNTA


def test_sin_nada_sustantivo_no_hay_pregunta_previa():
    assert followups.last_user_question(["ok", "listo", "  "]) is None
    assert followups.last_user_question([]) is None


def test_no_se_arrastra_un_tema_fuera_de_la_ventana():
    viejo = "¿Cómo consigno un vehículo?"
    historial = [viejo] + ["ok"] * followups.LOOKBACK_MESSAGES
    assert followups.last_user_question(historial) is None


def test_gana_la_pregunta_mas_reciente():
    historial = ["¿Cómo consigno?", "gracias", "¿Cuánto es la comisión?", "ya"]
    assert followups.last_user_question(historial) == "¿Cuánto es la comisión?"
