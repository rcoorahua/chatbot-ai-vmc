"""Deteccion de mensajes triviales (RF-021 / D-006, cerrada 2026-08-28): corre ANTES del
clasificador y resuelve sin llamada IA lo que no la amerita.

Que cubre y que no:
- saludo o agradecimiento SUELTOS → respuesta fija. "hola, cuanto es la comision" NO es
  trivial: trae una consulta y sigue al clasificador.
- repeticion: la decide el worker comparando con el hilo (aqui solo se normaliza el texto),
  porque este modulo es hoja y no lee la conversacion.
- spam por volumen: ya lo frena el rate limit de D-005 antes de llegar aqui.

El criterio es el mismo que en heuristics.py: ante la duda NO es trivial — el costo de tratar
una consulta real como saludo (no responderla) es mucho mayor que una llamada barata de mas.
"""

from __future__ import annotations

from backend.agent.heuristics import normalize

# Frases completas, no subcadenas: "buenas" es un saludo, "buenas ofertas tienen?" no.
# Se normalizan al importar con la misma funcion que el mensaje (tildes fuera, minusculas).
_GREETINGS = frozenset(
    normalize(phrase)
    for phrase in (
        "hola", "holaa", "holaaa", "ola", "buenas", "buenos dias", "buen dia",
        "buenas tardes", "buenas noches", "hey", "hello", "alo", "que tal", "como estas",
        "hola buenas", "hola buenos dias", "hola buenas tardes", "hola buenas noches",
        "hola que tal", "hola como estas",
    )
)

_THANKS = frozenset(
    normalize(phrase)
    for phrase in (
        "gracias", "muchas gracias", "mil gracias", "ok gracias", "ya gracias",
        "listo gracias", "perfecto gracias", "gracias por la ayuda", "thank you", "thanks",
        "ok", "okey", "okay", "vale", "listo", "perfecto", "genial", "buenisimo", "chevere",
        "adios", "chau", "chao", "hasta luego", "nos vemos",
    )
)

# Preguntas sobre la naturaleza del asistente (transparencia). Fijas porque el RAG no tiene
# evidencia sobre Subastin y sin esto "eres un bot?" derivaria a un asesor por falta de
# evidencia (RF-018), que es justo lo contrario de una respuesta transparente.
_IDENTITY = frozenset(
    normalize(phrase)
    for phrase in (
        "eres un bot", "eres un robot", "eres una ia", "eres una inteligencia artificial",
        "eres una maquina", "eres humano", "eres una persona", "eres real", "eres persona",
        "hablo con un bot", "hablo con un robot", "hablo con una persona", "hablo con un humano",
        "estoy hablando con un bot", "estoy hablando con una persona",
        "estoy hablando con un robot", "con quien hablo", "quien eres", "quien me habla",
        "que eres", "eres chatgpt", "eres gemini", "eres una ia o una persona",
        "eres un bot o una persona", "eres persona o bot", "eres bot", "eres robot",
        "me responde un bot", "me esta respondiendo un bot", "eres de verdad",
    )
)

# Un mensaje trivial es corto por definicion: si alguien escribio un parrafo, hay contenido.
_MAX_TRIVIAL_CHARS = 40


def match_trivial(message: str) -> str | None:
    """`"greeting"`, `"thanks"`, `"identity"` o `None`. Solo si TODO el mensaje es el
    saludo/cierre/pregunta de identidad."""
    text = normalize(message or "")
    if not text or len(text) > _MAX_TRIVIAL_CHARS:
        return None
    stripped = text.strip("!¡?¿.,;:() ")
    if stripped in _GREETINGS:
        return "greeting"
    if stripped in _THANKS:
        return "thanks"
    if stripped in _IDENTITY or stripped.removeprefix("hola ").strip() in _IDENTITY:
        return "identity"
    return None


def same_message(a: str, b: str) -> bool:
    """Igualdad para detectar repeticion (D-006): normalizada, para que "Hola??" y "hola"
    cuenten como el mismo mensaje."""
    left = normalize(a or "").strip("!¡?¿.,;:() ")
    right = normalize(b or "").strip("!¡?¿.,;:() ")
    return bool(left) and left == right
