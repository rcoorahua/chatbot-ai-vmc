"""Flujos guiados con quick replies — D-028, mapeo completo en MAPEO.md.

El problema que resuelven: el RAG busca con el texto del mensaje actual, y una respuesta
corta a una pregunta del bot ("En Vivo") no recupera nada por si sola (0 resultados sobre el
umbral, medido 2026-09-01). El flujo recuerda QUE dato se espera y, al recibirlo, busca con
una consulta canonica que si tiene evidencia (4 resultados, mejor score 0.913).

Este modulo es SOLO definiciones y funciones puras (regla de `backend/__init__.py`: las
integraciones hoja no importan dominio). Quien compone flujo + repositorio + mensajes es el
worker (`workers/ai_worker.py`), igual que con el resto del pipeline.

Detectar el flujo y mostrar botones NO llama a ningun modelo (reglas deterministas, costo
cero — regla llm-cost-optimizer); resolver el paso hace la misma unica llamada al redactor
que cualquier FAQ.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from backend.agent.heuristics import normalize

# Vigencia del flujo (MAPEO.md §2): la conversacion es permanente (D-003), el flujo no.
# Pasado esto, el estado se ignora y se limpia en la primera oportunidad.
FLOW_TTL_HOURS = 24

# Tipo de interaccion que el widget sabe dibujar (metadata del mensaje del bot).
QUICK_REPLIES = "QUICK_REPLIES"


@dataclass(frozen=True, slots=True)
class QuickReply:
    label: str  # lo que ve y envia el usuario (UI en español, T7)
    value: str  # el dato estructurado que valida el servidor (datos en ingles, T7)


@dataclass(frozen=True, slots=True)
class FlowStep:
    action_id: str
    slot: str
    prompt: str
    options: tuple[QuickReply, ...]
    # Consulta canonica por valor: lo que se manda al RAG cuando el paso queda resuelto.
    # Verificadas contra el indice real (2026-09-01): ambas con 4 resultados sobre el umbral.
    canonical_queries: dict[str, str] = field(default_factory=dict)

    def accepts(self, value: str) -> bool:
        """Enum cerrado por paso: editar el HTML no inventa acciones (security-guidance)."""
        return any(option.value == value for option in self.options)

    def label_for(self, value: str) -> str | None:
        for option in self.options:
            if option.value == value:
                return option.label
        return None


@dataclass(frozen=True, slots=True)
class FlowDefinition:
    name: str
    # Un solo paso por ahora (F-PART); una tupla para que agregar pasos no cambie la forma.
    steps: tuple[FlowStep, ...]

    def step(self, action_id: str) -> FlowStep | None:
        for candidate in self.steps:
            if candidate.action_id == action_id:
                return candidate
        return None


_SELECT_OFFER_TYPE = FlowStep(
    action_id="SELECT_OFFER_TYPE",
    slot="offer_type",
    prompt="¿En qué tipo de oferta quieres participar?",
    options=(
        QuickReply(label="Oferta En Vivo", value="LIVE"),
        QuickReply(label="Oferta Negociable", value="NEGOTIABLE"),
    ),
    canonical_queries={
        "LIVE": "Si quiero participar en una oferta En Vivo hoy, ¿qué tengo que hacer?",
        "NEGOTIABLE": (
            "¿Qué significa oferta Negociable y cómo inicio una negociación para participar?"
        ),
    },
)

_CONS_SELECT_OFFER_TYPE = FlowStep(
    action_id="SELECT_OFFER_TYPE",
    slot="offer_type",
    prompt="¿Para qué tipo de oferta quieres consignar?",
    options=(
        QuickReply(label="Oferta En Vivo", value="LIVE"),
        QuickReply(label="Oferta Negociable", value="NEGOTIABLE"),
    ),
    canonical_queries={
        "LIVE": "¿Cómo y cuánto debo consignar para poder participar en una oferta En Vivo?",
        "NEGOTIABLE": (
            "¿Cómo y cuánto debo consignar para poder participar en una oferta Negociable?"
        ),
    },
)

_SELECT_LIVE_STAGE = FlowStep(
    action_id="SELECT_LIVE_STAGE",
    slot="live_stage",
    prompt="¿En qué parte del proceso En Vivo estás?",
    options=(
        QuickReply(label="Antes de empezar", value="BEFORE"),
        QuickReply(label="Durante la puja", value="DURING"),
        QuickReply(label="Terminó el proceso", value="FINISHED"),
        QuickReply(label="Resulté ganador", value="WINNER"),
    ),
    canonical_queries={
        "BEFORE": (
            "Si quiero participar en una oferta En Vivo hoy, ¿qué tengo que hacer y cómo "
            "ingreso a la Sala?"
        ),
        "DURING": "¿Cómo envío mis bids durante el proceso En Vivo y cuántos bids puedo hacer?",
        "FINISHED": (
            "La oferta En Vivo terminó, ¿ahora qué sigue y cuándo me devuelven la consignación?"
        ),
        "WINNER": "Gané una oferta En Vivo, ¿cuáles son los siguientes pasos como ganador?",
    },
)

_SELECT_NEGO_STAGE = FlowStep(
    action_id="SELECT_NEGO_STAGE",
    slot="nego_stage",
    prompt="¿En qué punto está tu negociación?",
    options=(
        QuickReply(label="Envié mi propuesta", value="PROPOSAL_SENT"),
        QuickReply(label="Me aceptaron", value="ACCEPTED"),
        QuickReply(label="Contrapropuesta", value="COUNTER"),
        QuickReply(label="Rechazada", value="REJECTED"),
    ),
    canonical_queries={
        "PROPOSAL_SENT": (
            "Ya envié mi propuesta en una oferta Negociable, ¿dónde veo la respuesta del "
            "vendedor y el estado de la negociación?"
        ),
        "ACCEPTED": "El vendedor ha aceptado mi propuesta en la oferta Negociable, ¿qué hago?",
        "COUNTER": "El vendedor me ha enviado una contrapropuesta, ¿qué hago?",
        "REJECTED": "¿Qué pasa si el vendedor rechaza mi propuesta o yo rechazo la suya?",
    },
)

_SELECT_HAB_TOPIC = FlowStep(
    action_id="SELECT_HAB_TOPIC",
    slot="hab_topic",
    prompt="¡Felicitaciones! ¿Con qué parte del proceso te ayudo?",
    options=(
        QuickReply(label="Pagar la comisión", value="COMMISSION"),
        QuickReply(label="Subir documentos", value="DOCUMENTS"),
        QuickReply(label="Pagar la oferta", value="PAYMENT"),
        QuickReply(label="Mi comprobante", value="RECEIPT"),
    ),
    canonical_queries={
        "COMMISSION": (
            "Fui habilitado para comprar, ¿cómo se paga la comisión y dónde veo el porcentaje?"
        ),
        "DOCUMENTS": "¿Qué documentos debo adjuntar después de ser habilitado?",
        "PAYMENT": (
            "Ya pagué la comisión y subí los documentos, ¿cómo hago el pago de la oferta y "
            "qué sigue?"
        ),
        "RECEIPT": (
            "Terminé el proceso de compra de la oferta y necesito mi comprobante de pago "
            "(boleta o factura), ¿a quién y cómo lo solicito?"
        ),
    },
)

# Los 5 flujos de MAPEO.md §4.1, todos ACTIVOS (F-CONS/F-LIVE/F-NEGO/F-HAB activados
# 2026-09-01 por pedido de Aaron). Las consultas canonicas de cada valor estan verificadas
# contra el indice real — ver el bloque de verificacion en MAPEO.md.
# Confirmar el paso a un asesor (revision de D-029, 2026-09-02). No es un flujo del corpus
# como los de MAPEO.md: es una pregunta de si/no que el BOT abre cuando se queda sin
# evidencia, para no empujar el formulario sin preguntar. Se apoya en la misma maquinaria
# (transicion atomica, version que invalida botones viejos, vencimiento) porque el problema es
# el mismo: hay que recordar que se pregunto algo y validar la respuesta contra ese paso.
HANDOFF_CONFIRM = "HANDOFF_CONFIRM"

def _lexicon(*items: str) -> frozenset[str]:
    """El lexico pasa por la MISMA normalizacion que el mensaje, asi "sí", "si" y "SI" caen en
    la misma entrada sin duplicarlas a mano (heuristics.normalize)."""
    return frozenset(normalize(item) for item in items)


_CONFIRM_YES = _lexicon(
    "si", "sip", "claro", "dale", "ya", "por favor", "si por favor", "sí porfa", "porfa",
    "bueno", "ok", "okey", "vale", "de acuerdo", "quiero", "si quiero", "asesor",
    "si asesor", "conectame", "conectame con un asesor",
)
_CONFIRM_NO = _lexicon(
    "no", "nop", "no gracias", "no por ahora", "ahora no", "todavia no", "mejor no",
    "no hace falta", "no es necesario", "asi esta bien", "gracias", "no gracias por ahora",
)

_CONFIRM_HANDOFF = FlowStep(
    action_id="CONFIRM_HANDOFF",
    slot="confirm",
    # El texto que se publica NO es este: el worker manda el suyo (el de "no tengo ese dato",
    # `prompts.FAQ_NO_EVIDENCE_CONFIRM_RESPONSE`) para no partir la respuesta en dos mensajes.
    # Este queda como respaldo si algun dia se ofrece el paso desde otro sitio.
    prompt="¿Quieres que te conecte con un asesor del equipo?",
    options=(
        QuickReply(label="Sí, con un asesor", value="YES"),
        QuickReply(label="No, gracias", value="NO"),
    ),
)


FLOWS: dict[str, FlowDefinition] = {
    HANDOFF_CONFIRM: FlowDefinition(name=HANDOFF_CONFIRM, steps=(_CONFIRM_HANDOFF,)),
    "PARTICIPATION": FlowDefinition(name="PARTICIPATION", steps=(_SELECT_OFFER_TYPE,)),
    "CONSIGNMENT": FlowDefinition(name="CONSIGNMENT", steps=(_CONS_SELECT_OFFER_TYPE,)),
    "LIVE_STAGE": FlowDefinition(name="LIVE_STAGE", steps=(_SELECT_LIVE_STAGE,)),
    "NEGOTIATION_STAGE": FlowDefinition(name="NEGOTIATION_STAGE", steps=(_SELECT_NEGO_STAGE,)),
    "ENABLEMENT": FlowDefinition(name="ENABLEMENT", steps=(_SELECT_HAB_TOPIC,)),
}


# ───────────────────────────── Deteccion por reglas (sin IA) ─────────────────────────────

# "quiero participar", "como participo", "deseo participar en una subasta", "me interesa
# participar", "quiero ofertar/pujar/bidear". Sobre texto normalizado (minusculas y sin
# tildes, ver heuristics.normalize).
_PARTICIPATION_PATTERN = re.compile(
    r"\b(?:"
    r"(?:quiero|quisiera|deseo|me\s+interesa|como(?:\s+puedo|\s+hago\s+para)?)\s+"
    r"participar"
    r"|participar\s+en\s+(?:una?\s+)?(?:subasta|oferta|puja)"
    r"|quiero\s+(?:ofertar|pujar|bidear)"
    r"|como\s+participo"
    r")\b"
)

_LIVE_PATTERN = re.compile(r"\ben\s*vivo\b")
_NEGOTIABLE_PATTERN = re.compile(r"\bnegociabl\w*\b")

# "quiero consignar", "como consigno", "cuanto debo consignar". El verbo disparador tiene que
# estar CERCA de "consign": "cuando me devuelven la consignacion" (FAQ de devolucion) no
# lleva ninguno y no dispara.
_CONSIGNMENT_PATTERN = re.compile(
    r"\b(?:quiero|quisiera|deseo|necesito|debo|tengo\s+que|como|cuanto)\b"
    r"(?:\s+\w+){0,2}\s+consign\w+"
    r"|\bcomo\s+consigno\b"
)

# "me habilitaron", "fui habilitado", "que hago despues de la habilitacion".
_ENABLEMENT_PATTERN = re.compile(
    r"\b(?:me\s+habilitaron|(?:fui|he\s+sido|estoy|soy)\s+(?:un\s+)?"
    r"(?:ganador\s+)?habilitad[oa]|despues\s+de\s+la\s+habilitacion)\b"
)

# Negociacion EN CURSO: exige propuesta/contrapropuesta/negociacion — "como funciona la
# oferta negociable" es FAQ plana (o slot de F-PART) y no debe caer aqui.
_NEGOTIATION_PATTERN = re.compile(
    r"\bcontrapropuesta\b"
    r"|\b(?:mi|la)\s+negociacion\b"
    r"|\bpropuesta\b.{0,60}\b(?:acept\w+|rechaz\w+|respuesta|vendedor|estado)\b"
    r"|\b(?:acept\w+|rechaz\w+|envie|mande)\b.{0,40}\bpropuesta\b"
)

# Proceso En Vivo en curso: "en vivo" + señal de etapa o duda, o directamente "gane la
# oferta/subasta". "quiero participar en una en vivo" NO cae aqui (eso es F-PART y se
# chequea despues, pero este patron exige duda/etapa que ese texto no tiene).
_LIVE_STAGE_PATTERN = re.compile(
    r"\ben\s*vivo\b.{0,60}\b(?:que\s+hago|que\s+sigue|no\s+se\s+que|ayuda|como\s+va"
    r"|ya\s+empezo|por\s+empezar|termino|finalizo|cerro|gane|ganador)\b"
    r"|\b(?:que\s+hago|que\s+sigue|como\s+va)\b.{0,60}\ben\s*vivo\b"
    r"|\bgane\b.{0,40}\b(?:oferta|subasta|proceso)\b"
    r"|\b(?:resulte|sali|quede)\s+ganador\b|\bsoy\s+(?:el\s+)?ganador\b"
    r"|\bmejor\s+postor\b|\bganador\s+directo\b"
)


def _negated(keyword: str) -> re.Pattern:
    """Negacion hasta dos palabras antes del verbo clave: "no quiero participar", "ya no
    deseo consignar", "nunca voy a participar". Un "no" lejano no apaga la intencion.
    Hallado por los tests del motor (PR #79)."""
    return re.compile(rf"\b(?:no|tampoco|nunca|jamas)\b(?:\s+\w+){{0,2}}\s+{keyword}")


# Orden DELIBERADO, del disparador mas especifico al mas amplio: "quiero consignar para
# participar" es F-CONS (consignar manda), y F-PART va al final porque su patron es el mas
# generico. Cada entrada: (flujo, patron, palabra clave de negacion o None).
_TRIGGERS: tuple[tuple[str, re.Pattern, str | None], ...] = (
    ("CONSIGNMENT", _CONSIGNMENT_PATTERN, r"consign\w+"),
    ("ENABLEMENT", _ENABLEMENT_PATTERN, None),
    ("NEGOTIATION_STAGE", _NEGOTIATION_PATTERN, None),
    ("LIVE_STAGE", _LIVE_STAGE_PATTERN, None),
    ("PARTICIPATION", _PARTICIPATION_PATTERN, "participar"),
)


def detect_flow_start(text: str) -> str | None:
    """Nombre del flujo que el texto dispara, o None. Reglas, nunca un modelo.

    Una negacion cerca del verbo apaga ese disparador: quien dice "no quiero participar" no
    debe recibir botones de participacion — que lo atienda el pipeline normal (clasificador),
    donde "no puedo participar" ademas suele ser una FAQ legitima de problemas de acceso.
    """
    normalized = normalize(text or "")
    for flow_name, pattern, negation_keyword in _TRIGGERS:
        if negation_keyword and _negated(negation_keyword).search(normalized):
            continue
        if pattern.search(normalized):
            return flow_name
    return None


def extract_offer_type(text: str) -> str | None:
    """`LIVE` / `NEGOTIABLE` si el texto lo dice sin ambiguedad; None si no (o si dice ambos,
    que es justo el caso donde los botones desambiguan mejor que adivinar)."""
    normalized = normalize(text or "")
    live = bool(_LIVE_PATTERN.search(normalized))
    negotiable = bool(_NEGOTIABLE_PATTERN.search(normalized))
    if live == negotiable:  # ninguno o ambos
        return None
    return "LIVE" if live else "NEGOTIABLE"


def _single_match(candidates: dict[str, bool]) -> str | None:
    """El unico valor que matcheo, o None (cero o varios): la ambiguedad la desambiguan los
    botones, no una adivinanza — misma regla que extract_offer_type."""
    matched = [value for value, hit in candidates.items() if hit]
    return matched[0] if len(matched) == 1 else None


def _extract_live_stage(text: str) -> str | None:
    """Etapa del proceso En Vivo. Cada categoria reconoce ademas el LABEL de su boton
    ("Durante la puja" → durante/puja), para que el texto tecleado equivalga al click."""
    t = normalize(text or "")
    return _single_match({
        "BEFORE": bool(re.search(
            r"\bantes\b|\bpor\s+empezar\b|\bcuando\s+(?:empieza|inicia)\b|\btodavia\s+no\b",
            t)),
        "DURING": bool(re.search(
            r"\bdurante\b|\bpuja\w*\b|\bbid\w*\b|\bya\s+empezo\b|\ben\s+curso\b", t)),
        "FINISHED": bool(re.search(r"\btermino\b|\bfinalizo\b|\bcerro\b|\bacabo\b", t)),
        "WINNER": bool(re.search(r"\bgane\b|\bganador\w*\b|\bmejor\s+postor\b", t)),
    })


def _extract_nego_stage(text: str) -> str | None:
    """Etapa de la negociacion. OJO: "no me aceptaron" es un rechazo, no una aceptacion —
    por eso REJECTED absorbe el "acept" negado antes de que ACCEPTED lo cuente."""
    t = normalize(text or "")
    rejected = bool(re.search(
        r"\brechaz\w+\b|\bno\b(?:\s+\w+){0,2}\s+acept\w+", t))
    accepted = (not rejected) and bool(re.search(r"\bacept\w+\b", t))
    return _single_match({
        "COUNTER": bool(re.search(r"\bcontrapropuesta\b|\bcontraoferta\b", t)),
        "REJECTED": rejected,
        "ACCEPTED": accepted,
        "PROPOSAL_SENT": bool(re.search(
            r"\benvie\b|\bmande\b|\besperando\b|\ben\s+espera\b|\bsin\s+respuesta\b", t)),
    })


def _extract_hab_topic(text: str) -> str | None:
    """Tema de la habilitacion. PAYMENT exige "oferta" cerca del pago para no chocar con
    "pagar la comision" (que es COMMISSION)."""
    t = normalize(text or "")
    return _single_match({
        "COMMISSION": bool(re.search(r"\bcomision\b", t)),
        "DOCUMENTS": bool(re.search(r"\bdocumento\w*\b", t)),
        "PAYMENT": bool(re.search(r"\bpag\w+\b.{0,30}\boferta\b|\boferta\b.{0,30}\bpag\w+\b", t)),
        "RECEIPT": bool(re.search(r"\bcomprobante\b|\bboleta\b|\bfactura\b", t)),
    })


def _extract_confirm(text: str) -> str | None:
    """Si/no escrito a mano, para quien contesta en vez de clickear el boton.

    Solo acepta la respuesta SUELTA: "si, y ademas queria preguntarte otra cosa" no es un si
    limpio y es mejor dejarlo pasar como mensaje normal que derivar por error.
    """
    t = normalize(text or "").strip(" .!¡?¿,")
    if t in _CONFIRM_YES:
        return "YES"
    if t in _CONFIRM_NO:
        return "NO"
    return None


_SLOT_EXTRACTORS = {
    "offer_type": extract_offer_type,
    "live_stage": _extract_live_stage,
    "nego_stage": _extract_nego_stage,
    "hab_topic": _extract_hab_topic,
    "confirm": _extract_confirm,
}


def extract_slot_value(step: FlowStep, text: str) -> str | None:
    """El valor del slot del paso si el TEXTO lo resuelve (el usuario escribio en vez de
    clickear). Cada slot tiene su extractor; un slot sin extractor nunca se resuelve por
    texto (solo por boton)."""
    extractor = _SLOT_EXTRACTORS.get(step.slot)
    return extractor(text) if extractor else None


def validate_interaction(
    step: FlowStep, interaction: dict, *, current_version: int
) -> str | None:
    """El value del click SI corresponde al paso y la version vigentes; None en cualquier
    otro caso (accion inventada, boton de un flujo viejo, payload malformado).

    Un click invalido NO es un error: se ignora y el mensaje sigue el pipeline como texto
    normal — asi un boton de hace dias se degrada a una frase comun, no a un estado roto.
    """
    if not isinstance(interaction, dict):
        return None
    if interaction.get("action_id") != step.action_id:
        return None
    if interaction.get("flow_version") != current_version:
        return None
    value = interaction.get("value")
    if not isinstance(value, str) or not step.accepts(value):
        return None
    return value


def quick_replies_metadata(flow: FlowDefinition, step: FlowStep, version: int) -> dict:
    """La metadata del mensaje del bot que el widget dibuja como botones (MAPEO.md §3)."""
    return {
        "interaction": {
            "type": QUICK_REPLIES,
            "flow": flow.name,
            "action_id": step.action_id,
            "flow_version": version,
            "options": [
                {"label": option.label, "value": option.value} for option in step.options
            ],
        }
    }
