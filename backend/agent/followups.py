"""Continuidad conversacional para la consulta al RAG (RF-013 / RF-017).

El problema que resuelve, con datos reales de la consola de dev (2026-09-02):

    usuario  "¿Cómo me registro en VMC?"
    bot      "El primer paso es ingresar a vmcsubastas.com... ¿Me avisas cuando estés ahí
              para darte el siguiente paso?"          → RAG 4/4 sobre el umbral, mejor 0.875
    usuario  "Ya estoy ahi"
    bot      "No tengo ese dato a la mano..."         → RAG 4 hits, 0 sobre el umbral, 0.789

Los fragmentos recuperados en el segundo turno eran LOS CORRECTOS (el artículo "¡Registrarte
es fácil y rápido!"), pero puntuaron 0.789 y 0.781: "Ya estoy ahi" no se parece a nada por sí
solo. El redactor sí recibe el historial (`writer.write_answer(history=...)`), pero nunca
llega a correr porque antes se decide que no hay evidencia (RF-018).

O sea: el prompt del redactor promete continuidad ("un paso a la vez, pregunta si continuar",
`prompts.WRITER_SYSTEM_PROMPT`) y la recuperación era de un solo turno. Este módulo cierra esa
brecha: cuando el mensaje es una continuación, la consulta al índice se arma con la pregunta
que el usuario ya había hecho.

Determinista y gratis: son reglas sobre texto, sin llamada a ningún modelo (no gasta la cuota
de D-027 ni aparece en AIUsage). Es la misma política que `agent/heuristics.py`: reglas antes
que modelo, y ante la duda NO se decide — si no está claro que sea continuación, la consulta
se queda como la escribió el usuario, que es el comportamiento de siempre.

Esto NO es la máquina de estados de D-028 (`agent/flows.py`): aquella son flujos guiados con
botones y estado persistido en la conversación. Esto es solo la consulta que se le manda a
Pinecone; no guarda nada.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# Un mensaje más largo que esto ya se sostiene solo: aunque siga la conversación, tiene
# suficiente contenido para recuperar por sí mismo y mezclarlo solo agregaría ruido.
MAX_CONTINUATION_CHARS = 60
# Tope de la consulta: el embedding de `multilingual-e5-large` trabaja con textos cortos, y un
# párrafo entero dispersa la similitud en vez de concentrarla.
MAX_QUERY_CHARS = 300
# Cuántos mensajes atrás se busca la pregunta del usuario. Más allá, la conversación ya cambió
# de tema y arrastrarla sería peor que no hacer nada.
LOOKBACK_MESSAGES = 6

_WHITESPACE = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Minúsculas, sin tildes, espacios comprimidos (misma técnica que heuristics.py)."""
    decomposed = unicodedata.normalize("NFKD", (text or "").lower().strip())
    without_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return _WHITESPACE.sub(" ", without_marks)


def _phrases(*items: str) -> tuple[str, ...]:
    return tuple(normalize(item) for item in items)


# Confirmaciones y acuses: "ya hice lo que me dijiste". No aportan tema, solo posición.
_ACKNOWLEDGEMENTS = _phrases(
    "ya estoy", "ya estoy ahi", "ya estoy aqui", "aqui estoy", "ahi estoy", "ya llegue",
    "ya entre", "ya ingrese", "ya lo hice", "ya esta", "ya estaria", "listo", "hecho",
    "ok", "oka", "okey", "vale", "dale", "perfecto", "ya", "si", "sip", "claro",
    "correcto", "asi es", "afirmativo", "entendido", "de acuerdo",
)

# Pedidos explícitos de seguir: el usuario pide el resto de algo que ya se estaba explicando.
_CONTINUATIONS = _phrases(
    "y luego", "y despues", "y ahora", "y entonces", "que sigue", "cual es el siguiente",
    "siguiente paso", "el siguiente", "continua", "continuemos", "sigue", "sigamos",
    "adelante", "mas detalles", "cuentame mas", "explicame mas", "y que mas", "que mas",
)


# Un mensaje que ya es una PREGUNTA se sostiene solo aunque sea corto y aunque el bot acabara
# de preguntar algo: quien contesta "¿cuánto es la comisión?" no está respondiendo, está
# cambiando de tema. Sin esta salvedad, la consulta mezclaría los dos temas y recuperaría peor
# que sin contextualizar nada.
_INTERROGATIVES = (
    "que ", "qué ", "como ", "cuanto", "cuando", "donde", "quien", "cual", "por que",
    "porque ", "para que", "se puede", "puedo ", "hay ",
)


def _looks_like_question(normalized: str) -> bool:
    return normalized.endswith("?") or normalized.startswith(_INTERROGATIVES)


@dataclass(frozen=True, slots=True)
class Query:
    """La consulta que se le manda al índice y de dónde salió.

    `contextualized` es False cuando se usó el texto tal cual: sirve para leer en los logs si
    la regla intervino, sin tener que reproducir la conversación.
    """

    text: str
    contextualized: bool
    rule: str | None = None


def is_continuation(text: str, *, bot_asked: bool = False) -> tuple[bool, str | None]:
    """¿Este mensaje solo tiene sentido pegado a lo anterior? Devuelve `(sí/no, regla)`.

    Tres formas de decidir, de la más segura a la más contextual:
    1. es un acuse o una confirmación ("ya estoy ahí", "listo", "sí");
    2. pide explícitamente seguir ("y luego", "¿qué sigue?");
    3. es corto, el bot acababa de preguntar algo Y el mensaje no es a su vez una pregunta:
       ahí sí está respondiendo, y su sentido depende de lo que se le preguntó.

    La tercera lleva dos condiciones justamente para no marcar como continuación cualquier
    mensaje corto: "¿cuánto es la comisión?" es corto, llega después de una pregunta del bot
    y se sostiene perfectamente solo — arrastrarle el tema anterior empeoraría la búsqueda.
    """
    con_signos = normalize(text).strip()
    limpio = con_signos.strip(" .!¡?¿,")
    if not limpio:
        return False, None
    if len(limpio) > MAX_CONTINUATION_CHARS:
        return False, None
    if limpio in _ACKNOWLEDGEMENTS:
        return True, "acuse"
    # Antes de descartar preguntas: "¿y luego?" es una pregunta Y una continuación.
    if any(limpio.startswith(frase) for frase in _CONTINUATIONS):
        return True, "pide_seguir"
    if bot_asked and not _looks_like_question(con_signos):
        return True, "responde_al_bot"
    return False, None


# Categorías Unicode que se descartan al buscar el signo de cierre: símbolos (los emoji son
# `So`), modificadores de símbolo (los tonos de piel), marcas sin espaciado (los selectores de
# variación) y los invisibles de formato (el ZWJ que une emoji compuestos).
_TRAILING_DECORATION = frozenset({"So", "Sk", "Sm", "Mn", "Cf", "Zs"})


def bot_asked_something(last_bot_message: str | None) -> bool:
    """El último mensaje del bot terminó preguntando algo.

    Se mira el final y no todo el texto porque una explicación puede contener una pregunta
    retórica en medio ("¿qué necesitas para participar? Necesitas..."); lo que abre turno es
    la pregunta con la que se cierra.

    Y se ignora el emoji final, que es lo que hacía inútil esta función: D-025 permite UN emoji
    al final del mensaje, así que casi toda pregunta real del bot llega como
    "¿Deseas que te explique el siguiente paso? 🚚" y un `endswith("?")` a secas daba False
    (visto en una conversación real el 2026-09-02). Solo se descarta decoración: si el mensaje
    termina en punto o en cifra, sigue sin ser una pregunta.
    """
    texto = (last_bot_message or "").rstrip()
    while texto and unicodedata.category(texto[-1]) in _TRAILING_DECORATION:
        texto = texto[:-1].rstrip()
    return texto.endswith("?")


def build_query(
    text: str, *, previous_question: str | None, last_bot_message: str | None = None
) -> Query:
    """La consulta para el RAG: el texto tal cual, o la pregunta previa del usuario si esto es
    una continuación.

    Se busca la pregunta previa **SOLA**, sin pegarle lo que el usuario acaba de escribir.
    Medido contra el índice real (2026-09-02), con "Hola como me registro" de tema:

        consulta                                sobre el umbral   mejor
        "Hola como me registro"                      4/4          0.859
        "Hola como me registro sí"                   1/4          0.841
        "Hola como me registro y luego?"             4/4          0.849
        "Hola como me registro ya le di clic"        1/4          0.843

    Una continuación no cambia el tema, así que tampoco debe cambiar la evidencia: sus
    palabras ("sí", "listo", "ya le di clic") no describen nada del corpus y solo dispersan el
    embedding. Lo que cambia entre turnos es lo que el REDACTOR dice sobre esa misma
    evidencia, y para eso recibe el texto original más el historial.

    Tampoco se usa la respuesta del bot: está redactada con el corpus, así que meterla acerca
    la consulta a los fragmentos ya usados en vez de a los que faltan.
    """
    original = (text or "").strip()
    continuacion, rule = is_continuation(
        original, bot_asked=bot_asked_something(last_bot_message)
    )
    anterior = (previous_question or "").strip()
    if not continuacion or not anterior:
        return Query(text=original, contextualized=False)
    return Query(text=anterior[:MAX_QUERY_CHARS], contextualized=True, rule=rule)


def last_user_question(previous_texts: list[str]) -> str | None:
    """La última pregunta del usuario que se sostiene sola, mirando hacia atrás.

    `previous_texts` son sus mensajes anteriores en orden cronológico (sin el actual). Se
    saltan los que son a su vez continuaciones: encadenar "ya estoy ahí" sobre "listo" no
    daría tema ninguno, hay que llegar a la pregunta de verdad.
    """
    for candidato in reversed(previous_texts[-LOOKBACK_MESSAGES:]):
        limpio = (candidato or "").strip()
        if not limpio:
            continue
        continuacion, _ = is_continuation(limpio)
        if not continuacion:
            return limpio
    return None
