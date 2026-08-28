"""Capa determinista del clasificador de intencion (RF-015/016): reglas antes que Haiku.

Resuelve sin llamada IA los mensajes inequivocos (pedir un asesor, amenazar con Indecopi,
buscar vehiculos por marca) y produce una señal de tono para los ambiguos, que decide Haiku.
Criterio para que una regla decida: equivocarse debe costar mas que la llamada que evita. Un
falso positivo aqui manda al usuario a un asesor o al catalogo por error; un falso negativo
solo cuesta una llamada barata. Por eso ante la duda la regla NO decide y devuelve `None`.

El lexico se escribe en español natural (con tildes) y se normaliza al importar con la misma
funcion que normaliza el mensaje, de modo que "pásame", "pasame" y "PASAME" caen en la misma
regla sin duplicar entradas.

Fuera de este modulo, a proposito:
- Subtipos de escalacion (legal, subasta en vivo, B2B...): dependen de la taxonomia D-008.
  Aqui solo se decide el binario "necesita asesor".
- Saludos, spam y repeticion (RF-021): es la politica D-006 y corre antes de clasificar.
- Consultas de datos personales -> ADVISOR (RF-016): que campos son "no habilitados" es D-010.
"""

import re
import unicodedata
from dataclasses import dataclass

from backend.agent.intents import Intent


@dataclass(frozen=True, slots=True)
class HeuristicResult:
    """Salida de `classify_by_rules`.

    `intent` en `None` significa "las reglas no deciden" y el mensaje sigue a Haiku. `rule`
    nombra la regla que disparo para que AIUsage registre la decision con costo cero y se
    pueda medir cuanto trafico evita la llamada IA. `frustration_hint` no cambia la ruta: se
    inyecta al prompt de Haiku para que pese el tono en vez de solo el contenido literal.
    """

    intent: Intent | None
    rule: str | None
    frustration_hint: bool


_WHITESPACE = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Minusculas, sin tildes ni diereses, espacios comprimidos.

    NFKD separa cada letra acentuada en letra base mas marca combinante; descartar las marcas
    deja el texto sin acentos. La eñe tambien pierde su marca ("piña" -> "pina"): es
    aceptable porque el lexico pasa por la misma funcion y ninguna entrada colisiona.
    """
    decomposed = unicodedata.normalize("NFKD", text.lower().strip())
    without_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return _WHITESPACE.sub(" ", without_marks)


def _phrases(*items: str) -> tuple[str, ...]:
    return tuple(normalize(item) for item in items)


# ----------------------------------------------------------------------------------------
# ADVISOR — alta confianza. Cada grupo es una regla con nombre propio: el nombre es el motivo
# de derivacion, que es lo que un asesor querra ver en el ticket y lo que AIUsage registra.
# Se buscan frases, no palabras sueltas: "asesor" solo aparece en preguntas FAQ legitimas
# ("¿el asesor me llama despues de ganar?") y dispararia derivaciones falsas.
# ----------------------------------------------------------------------------------------
_ADVISOR_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "advisor_request",
        _phrases(
            "hablar con alguien", "hablar con una persona", "hablar con un humano",
            "hablar con un asesor", "hablar con el asesor", "hablar con un agente",
            "persona real", "persona de verdad", "alguien de verdad", "alguien real",
            "atención humana", "soporte humano", "agente humano", "ayuda humana",
            "atiéndeme una persona", "me atiende una persona", "me atiende un humano",
        ),
    ),
    (
        "bot_rejection",
        _phrases(
            "no quiero hablar con una máquina", "no quiero hablar con el bot",
            "no quiero un bot", "deja de responder", "este bot no sirve", "el bot no sirve",
            "no me sirve este bot", "bot inútil", "el bot no me entiende",
            "este bot no entiende", "tu bot es una vaina", "vaina de bot", "bot de m",
        ),
    ),
    (
        "voice_channel",
        _phrases(
            "a qué número llamo", "dame un teléfono", "dame el número", "número para llamar",
            "quiero llamar", "puedo llamar a alguien",
        ),
    ),
    (
        "legal_threat",
        _phrases(
            "indecopi", "libro de reclamaciones", "libro de reclamos", "voy a denunciar",
            "denuncia formal", "quejarme formalmente", "quiero hacer un reclamo",
            "quiero reclamar", "voy a reclamar",
        ),
    ),
    # Solo formas acusatorias. "¿es una estafa?" o "¿como se que no es fraude?" son preguntas
    # de confianza que el bot debe responder con empatia, no derivar.
    (
        "fraud_accusation",
        _phrases(
            "son una estafa", "son estafadores", "unos estafadores", "puros estafadores",
            "me estafaron", "están robando", "me robaron", "es un fraude",
            "publicidad engañosa",
        ),
    ),
    (
        "hostility",
        _phrases(
            "me tienen harto", "me tienen harta", "estoy harto", "estoy harta", "estoy asado",
            "estoy asada", "pésimo servicio", "mal servicio", "horrible servicio",
            "porquería de servicio", "servicio inservible",
        ),
    ),
    # Peruanismos que acusan evasion: quien los usa ya no espera respuesta del bot.
    (
        "peruvian_complaint",
        _phrases("puro floro", "me estás floreando", "me floreas", "tas floreando"),
    ),
    (
        "funds_claim",
        _phrases(
            "perdí mi consignación", "perdí mi garantía", "no aparece mi garantía",
            "no aparece mi consignación", "devuelvan mi dinero", "quiero mi dinero",
            "devuélveme mi plata", "devuélvanme mi plata", "quiero mi plata de vuelta",
        ),
    ),
)

# Verbo de solicitud seguido, a lo sumo cuatro palabras despues, de un sustantivo de persona.
# La distancia acotada evita el falso positivo del original ("quiero saber si una persona
# jurídica puede registrarse" tiene verbo y sustantivo, pero no pide un asesor); el lookahead
# excluye "persona jurídica/natural", que son conceptos del registro y no personas.
# Se aplica sobre texto ya normalizado, por eso las alternativas van sin tildes.
_ADVISOR_REQUEST_PATTERN = re.compile(
    r"\b(?:quiero|necesito|dame|pasame|pasenme|comunicame|comunicarme|transfiereme|"
    r"derivame|atiendame|que me atienda)\b"
    r"(?:\W+\w+){0,4}?\W+"
    r"(?:asesor|asesora|agente|humano|humana|ejecutivo|ejecutiva|representante|operador|"
    r"persona(?!\s+(?:juridica|natural))|alguien)\b"
)

# ----------------------------------------------------------------------------------------
# CATALOG — alta confianza solo cuando el mensaje habla exclusivamente de encontrar
# vehiculos. Si ademas menciona un proceso de la plataforma (participar, consignar,
# registrarse, pagar...) la pregunta es sobre el proceso y la decide Haiku: el original
# clasificaba "quiero participar en un Kia Picanto que vi en su web" como busqueda de stock.
# Son raices, no palabras: "particip" cubre participar/participando/participación.
# ----------------------------------------------------------------------------------------
_PROCESS_STEMS = _phrases(
    "particip", "puj", "ofert", "consign", "registr", "comisi", "subascoin", "billetera",
    "saldo", "visita", "inspecc", "cuenta", "gané", "adjudic", "ganador", "pag", "deuda",
    "sanci", "devoluci", "vi en", "lo vi", "la vi", "ese carro", "ese auto", "esa camioneta",
    "ese vehículo", "me interesa ese", "me interesa esa", "en esa subasta", "está listado",
    "aparece en", "lo encontré",
)

# Los tres patrones de abajo tambien corren sobre texto normalizado (sin tildes).
_SEARCH_SIGNAL_PATTERN = re.compile(
    r"\b(?:tienen|tienes|hay|busco|buscando|buscamos|quiero ver|muestrame|muestren|mostrar|"
    r"listar|lista de|catalogo|inventario|stock|disponible|disponibles|que carros|"
    r"cuanto vale|cuanto cuesta|precio de)\b"
)

# Sustantivos con limite de palabra y plural opcional: sin el limite, "auto" dispararia en
# "automático" y "moto" en "motor".
_VEHICLE_NOUN_PATTERN = re.compile(
    r"\b(?:carro|auto|vehiculo|camioneta|unidad|moto|camion|furgon)(?:s|es)?\b"
    r"|\b(?:suv|pickup|4x4)\b"
)

# Marca o modelo es señal suficiente por si sola: nadie escribe "hilux" para preguntar por
# comisiones, y si lo hace las raices de proceso lo interceptan antes.
_MAKE_OR_MODEL_PATTERN = re.compile(
    r"\b(?:toyota|kia|hyundai|chevrolet|nissan|honda|mazda|suzuki|ford|volkswagen|mitsubishi|"
    r"subaru|jeep|changan|great wall|peugeot|renault|volvo|isuzu|bmw|mercedes|audi|dfsk|foton|"
    r"haval|geely|byd|jac|"
    r"hilux|yaris|corolla|fortuner|rav4|picanto|sportage|tucson|rio|accent|creta|sentra|versa|"
    r"frontier|civic|cr-v|crv|mazda3|cx-5|cx5|vitara|swift|ranger|amarok|l200|outlander)\b"
)

# ----------------------------------------------------------------------------------------
# Señales de media confianza. No deciden ruta: "necesito ayuda para registrarme" no es un
# handoff, pero "ya van 3 veces que sale error" merece que Haiku mire el tono. Incluye el
# abandono transaccional ("da igual", "ya fue"): el original lo tenia como alta confianza en
# codigo muerto, asi que no hay evidencia de su precision; se promueve cuando el golden set
# lo respalde. Quedan fuera "ya", "ok", "dale": dispararian en casi toda respuesta corta y
# esas ya se resuelven con el ultimo mensaje del asistente como contexto.
# ----------------------------------------------------------------------------------------
_FRUSTRATION_PHRASES = _phrases(
    "no funciona", "no carga", "error", "falla", "fallo", "no puedo", "no me deja",
    "no me sale", "al toque", "urgente", "urgentemente", "rápido", "ya van", "cuántas veces",
    "otra vez", "de nuevo", "sigo sin", "todavía no", "no aparece", "no veo", "no encuentro",
    "asado", "asada", "qué palta", "qué yuca", "qué piña", "qué lenteja", "malísimo",
    "horrible", "terrible", "pésimo", "no sirve", "no ayuda", "no me estás ayudando",
    "no me entiendes",
    "da igual", "olvídalo", "ya no quiero", "ya fue", "déjalo ahí", "me rindo",
    "mucho trámite", "muy complicado", "me desanimé",
)

# Sobre el texto original, no el normalizado: la normalizacion pierde las mayusculas.
_SHOUTING_PATTERN = re.compile(r"^[A-ZÁÉÍÓÚÑ\s!?¡¿.,0-9]{15,}$")
_EXCESSIVE_PUNCTUATION_PATTERN = re.compile(r"[!?]{3,}")


def classify_by_rules(message: str) -> HeuristicResult:
    """Aplica las reglas en orden de costo del error: ADVISOR antes que CATALOG.

    Un mensaje con señales de ambas ("¿tienen Hilux? no me sirve este bot, pásame con
    alguien") va al asesor: dejar a alguien molesto en el catalogo es peor que mandar una
    busqueda de vehiculos a un humano.
    """
    original = (message or "").strip()
    if not original:
        return HeuristicResult(intent=None, rule=None, frustration_hint=False)

    text = normalize(original)
    hint = _has_frustration_signals(original, text)

    advisor_rule = _match_advisor(text)
    if advisor_rule:
        return HeuristicResult(intent=Intent.ADVISOR, rule=advisor_rule, frustration_hint=hint)

    catalog_rule = _match_catalog(text)
    if catalog_rule:
        return HeuristicResult(intent=Intent.CATALOG, rule=catalog_rule, frustration_hint=hint)

    return HeuristicResult(intent=None, rule=None, frustration_hint=hint)


def _match_advisor(text: str) -> str | None:
    for rule, phrases in _ADVISOR_RULES:
        if any(phrase in text for phrase in phrases):
            return rule
    if _ADVISOR_REQUEST_PATTERN.search(text):
        return "advisor_request"
    return None


def _match_catalog(text: str) -> str | None:
    if any(stem in text for stem in _PROCESS_STEMS):
        return None
    if _MAKE_OR_MODEL_PATTERN.search(text):
        return "catalog_make_or_model"
    if _SEARCH_SIGNAL_PATTERN.search(text) and _VEHICLE_NOUN_PATTERN.search(text):
        return "catalog_search"
    return None


def _has_frustration_signals(original: str, text: str) -> bool:
    return (
        any(phrase in text for phrase in _FRUSTRATION_PHRASES)
        or bool(_SHOUTING_PATTERN.match(original))
        or bool(_EXCESSIVE_PUNCTUATION_PATTERN.search(original))
    )
