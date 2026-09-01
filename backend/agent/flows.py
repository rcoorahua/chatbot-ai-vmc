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

# F-PART es el unico flujo ACTIVO. F-CONS / F-LIVE / F-NEGO / F-HAB estan mapeados en
# MAPEO.md §4.1 y se activan agregando su FlowDefinition aqui — el motor no cambia.
FLOWS: dict[str, FlowDefinition] = {
    "PARTICIPATION": FlowDefinition(name="PARTICIPATION", steps=(_SELECT_OFFER_TYPE,)),
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


def detect_flow_start(text: str) -> str | None:
    """Nombre del flujo que el texto dispara, o None. Reglas, nunca un modelo."""
    if _PARTICIPATION_PATTERN.search(normalize(text or "")):
        return "PARTICIPATION"
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


def extract_slot_value(step: FlowStep, text: str) -> str | None:
    """El valor del slot del paso si el TEXTO lo resuelve (el usuario escribio en vez de
    clickear). Hoy todos los pasos activos usan offer_type."""
    if step.slot == "offer_type":
        return extract_offer_type(text)
    return None


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
