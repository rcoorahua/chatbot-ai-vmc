"""Taxonomía de tickets — ⚠️ PROPUESTA DE AARON, D-008 SIGUE ABIERTA (Silvana + Julio).

Los 12 `problem_type` de abajo salen del análisis del corpus del Centro de Ayuda (22
artículos, 111 preguntas) documentado en **[MAPEO.md](../../MAPEO.md) §8**: son los motivos
por los que un usuario realmente necesita a un humano. Se implementan aquí para que el módulo
de tickets exista y se pueda probar de punta a punta; **no cierran D-008**.

Qué significa "propuesta" en el código, y no solo en un comentario:
- toda la taxonomía vive en ESTE módulo (enums, categoría, prioridad y datos mínimos), así que
  cerrar D-008 con otra lista es editar un archivo, no rastrear literales por el backend;
- el `problem_type` que ponen las reglas es una **sugerencia**: el ticket guarda quién lo
  decidió (`classification_source`) y el asesor lo confirma o lo corrige (RF-049: la
  taxonomía no se edita desde la UI, pero el tipo de UN ticket sí);
- `GET /advisor/taxonomy` la publica para que la app del asesor dibuje los selects sin
  copiar la lista.

Módulo PURO (sin DynamoDB ni FastAPI) y sin importar `agent`: la regla de dependencias de
`backend/__init__.py` prohíbe que el dominio llame a una integración. Por eso las reglas por
palabras clave se escriben aquí y no se reusa `agent/heuristics.py`.

Criterio de las reglas (el mismo de heuristics.py): ante la duda NO se decide. Equivocar el
tipo le cuesta al asesor una corrección; dejarlo en `OTHER` solo le cuesta un vistazo. Por eso
`FORMAL_COMPLAINT` exige la frase fuerte ("libro de reclamaciones", "Indecopi") y no la
palabra "reclamo" suelta, que aparece en cualquier queja de pago.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from enum import StrEnum

# ───────────────────────────────── Enums de la taxonomía ─────────────────────────────────


class ProblemType(StrEnum):
    """Por qué el caso necesita un humano (MAPEO.md §8). `OTHER` es la salida honesta: el
    asesor lo re-clasifica al cerrar y esa corrección es el dato que mide la propuesta."""

    PAYMENT_ISSUE = "PAYMENT_ISSUE"
    REFUND_REQUEST = "REFUND_REQUEST"
    DEBT_DISPUTE = "DEBT_DISPUTE"
    SANCTION_APPEAL = "SANCTION_APPEAL"
    ENABLEMENT_ISSUE = "ENABLEMENT_ISSUE"
    RECEIPT_REQUEST = "RECEIPT_REQUEST"
    ACCOUNT_ACCESS = "ACCOUNT_ACCESS"
    RISK_CATEGORY_DISPUTE = "RISK_CATEGORY_DISPUTE"
    VISIT_ISSUE = "VISIT_ISSUE"
    PLATFORM_BUG = "PLATFORM_BUG"
    FORMAL_COMPLAINT = "FORMAL_COMPLAINT"
    OTHER = "OTHER"


class Category(StrEnum):
    """Agrupación operativa: es por lo que un asesor filtra su bandeja. `GENERAL` existe
    porque `OTHER` necesita una categoría concreta (MAPEO.md la deja en blanco)."""

    BILLING = "BILLING"
    COMPLIANCE = "COMPLIANCE"
    PURCHASE = "PURCHASE"
    ACCOUNT = "ACCOUNT"
    LOGISTICS = "LOGISTICS"
    TECHNICAL = "TECHNICAL"
    GENERAL = "GENERAL"


class Priority(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class Tag(StrEnum):
    """Etiquetas transversales (D-009, también abierta): cruzan tipos y sirven para filtrar.

    `RECURRENTE` NO se detecta sola: "mismo usuario, mismo problema, segunda vez" necesitaría
    un índice de Tickets por usuario que hoy no existe (y agregar un GSI es una decisión de
    modelo, PLAN.md §4 ajuste 7). La pone el asesor.
    """

    EN_VIVO = "EN_VIVO"
    NEGOCIABLE = "NEGOCIABLE"
    GANADOR = "GANADOR"
    PLAZO_CORRIENDO = "PLAZO_CORRIENDO"
    RECURRENTE = "RECURRENTE"


class TicketStatus(StrEnum):
    """Espejo del estado de la conversación escalada (D-029): PENDING mientras espera asesor,
    IN_PROGRESS cuando alguien la tomó, CLOSED al cerrarla."""

    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    CLOSED = "CLOSED"


# Prioridades ordenadas de menor a mayor: `_escalate` sube un escalón, sin pasarse de HIGH.
_PRIORITY_ORDER = (Priority.LOW, Priority.MEDIUM, Priority.HIGH)

# Etiquetas que suben la prioridad un escalón. Regla general en vez de un caso especial por
# tipo: lo que urge es que algo CORRE (un proceso en vivo, un plazo de habilitación o pago).
# Es lo que MAPEO.md §8 anota como "Alta durante un proceso En Vivo" y "hay plazos que corren".
_ESCALATING_TAGS = (Tag.EN_VIVO, Tag.PLAZO_CORRIENDO)


# ───────────────────────────────── Datos mínimos por tipo ─────────────────────────────────


@dataclass(frozen=True, slots=True)
class RequiredField:
    """Un dato que el asesor necesita para trabajar el ticket (RF-024).

    `name` en inglés (dato, T7) y `label` en español (lo lee una persona). No se le piden al
    usuario en un segundo formulario: se listan como `missing_data` del ticket para que el
    asesor sepa qué preguntar, y él los registra al obtenerlos.
    """

    name: str
    label: str


@dataclass(frozen=True, slots=True)
class ProblemTypeSpec:
    problem_type: ProblemType
    category: Category
    priority: Priority
    # Cuándo se abre, en las palabras del corpus. Viaja a la app del asesor como ayuda del
    # select: sin esto, elegir entre 12 códigos en inglés es adivinar.
    when: str
    required: tuple[RequiredField, ...] = field(default_factory=tuple)


def _req(*pairs: tuple[str, str]) -> tuple[RequiredField, ...]:
    return tuple(RequiredField(name=name, label=label) for name, label in pairs)


# La tabla de MAPEO.md §8, hecha código. Cerrar D-008 = editar ESTO.
TAXONOMY: dict[ProblemType, ProblemTypeSpec] = {
    spec.problem_type: spec
    for spec in (
        ProblemTypeSpec(
            problem_type=ProblemType.PAYMENT_ISSUE,
            category=Category.BILLING,
            priority=Priority.HIGH,
            when="Pagó y no se refleja, problemas con el código de pago, cobro duplicado",
            required=_req(
                ("offer_id", "Id de la oferta"),
                ("payment_method", "Medio de pago"),
                ("payment_date", "Fecha del pago"),
                ("amount", "Monto"),
            ),
        ),
        ProblemTypeSpec(
            problem_type=ProblemType.REFUND_REQUEST,
            category=Category.BILLING,
            priority=Priority.HIGH,
            when="Pide que le devuelvan saldo o una consignación no liberada",
            required=_req(
                ("amount", "Monto"),
                ("currency", "Moneda original"),
                ("transaction_date", "Fecha de la recarga o consignación"),
            ),
        ),
        ProblemTypeSpec(
            problem_type=ProblemType.DEBT_DISPUTE,
            category=Category.BILLING,
            priority=Priority.MEDIUM,
            when="No entiende o no acepta una deuda, quiere regularizarla para participar",
            required=_req(
                ("offer_id", "Id de la oferta que la originó"),
                ("amount", "Monto"),
            ),
        ),
        ProblemTypeSpec(
            problem_type=ProblemType.SANCTION_APPEAL,
            category=Category.COMPLIANCE,
            priority=Priority.HIGH,
            when="Apela una sanción: no pudo entrar a la sala, el proceso cerró sin que pujara",
            required=_req(
                ("process_id", "Id del proceso"),
                ("occurred_at", "Fecha y hora"),
                ("evidence", "Evidencia del problema"),
            ),
        ),
        ProblemTypeSpec(
            problem_type=ProblemType.ENABLEMENT_ISSUE,
            category=Category.PURCHASE,
            priority=Priority.HIGH,
            when="Ganó y la habilitación está trabada: documentos rechazados o sin respuesta",
            required=_req(
                ("offer_id", "Id de la oferta ganada"),
                ("blocked_step", "Qué paso está trabado"),
            ),
        ),
        ProblemTypeSpec(
            problem_type=ProblemType.RECEIPT_REQUEST,
            category=Category.PURCHASE,
            priority=Priority.LOW,
            when="Pide su boleta o factura de un proceso terminado",
            required=_req(
                ("offer_id", "Id de la oferta"),
                ("tax_id", "Razón social y RUC, si es factura"),
            ),
        ),
        ProblemTypeSpec(
            problem_type=ProblemType.ACCOUNT_ACCESS,
            category=Category.ACCOUNT,
            priority=Priority.MEDIUM,
            when="No puede registrarse o entrar: formulario que rechaza, contraseña que no llega",
            required=_req(
                ("registered_email", "Correo registrado"),
                ("error_message", "Mensaje de error"),
            ),
        ),
        ProblemTypeSpec(
            problem_type=ProblemType.RISK_CATEGORY_DISPUTE,
            category=Category.ACCOUNT,
            priority=Priority.MEDIUM,
            when="Reclama su Riesgo Usuario, sus Puntos VMC o un canje que no se aplicó",
        ),
        ProblemTypeSpec(
            problem_type=ProblemType.VISIT_ISSUE,
            category=Category.LOGISTICS,
            priority=Priority.MEDIUM,
            when="No puede agendar una visita o una inspección mecánica",
            required=_req(
                ("offer_id", "Id de la oferta"),
                ("desired_date", "Fecha deseada"),
            ),
        ),
        ProblemTypeSpec(
            problem_type=ProblemType.PLATFORM_BUG,
            category=Category.TECHNICAL,
            priority=Priority.MEDIUM,  # con EN_VIVO sube a HIGH (ver `resolve_priority`)
            when="La plataforma falla: la sala no carga, los bids no entran, errores al pujar",
            required=_req(
                ("device", "Dispositivo y navegador"),
                ("process_id", "Id del proceso"),
                ("occurred_at", "Hora"),
            ),
        ),
        ProblemTypeSpec(
            problem_type=ProblemType.FORMAL_COMPLAINT,
            category=Category.COMPLIANCE,
            priority=Priority.HIGH,
            when="Reclamo formal o libro de reclamaciones: tiene plazo legal",
            required=_req(("complaint_detail", "Descripción del reclamo")),
        ),
        ProblemTypeSpec(
            problem_type=ProblemType.OTHER,
            category=Category.GENERAL,
            priority=Priority.MEDIUM,
            when="No calza en ningún tipo; el asesor lo re-clasifica al cerrar",
        ),
    )
}


def spec_for(problem_type: ProblemType | str) -> ProblemTypeSpec:
    """La ficha de un tipo. Un tipo desconocido (fila vieja, D-008 cerrada con otra lista) cae
    en OTHER en vez de reventar: el ticket sigue siendo atendible."""
    try:
        return TAXONOMY[ProblemType(problem_type)]
    except ValueError:
        return TAXONOMY[ProblemType.OTHER]


def missing_data(problem_type: ProblemType | str, collected: dict | None) -> list[str]:
    """Datos mínimos del tipo que todavía no están (RF-024). El asesor los va registrando."""
    tiene = {key for key, value in (collected or {}).items() if str(value).strip()}
    return [f.name for f in spec_for(problem_type).required if f.name not in tiene]


def resolve_priority(
    problem_type: ProblemType | str, tags: list[str] | tuple[str, ...]
) -> Priority:
    """Prioridad base del tipo, subida un escalón si algo está corriendo (`_ESCALATING_TAGS`).

    Es lo que hace que un `PLATFORM_BUG` durante un En Vivo salga por encima de uno reportado
    en frío: el proceso corre en tiempo real y una falla de sala termina en apelación segura
    (MAPEO.md §8).
    """
    base = spec_for(problem_type).priority
    if any(tag in _ESCALATING_TAGS for tag in tags):
        return _PRIORITY_ORDER[min(_PRIORITY_ORDER.index(base) + 1, len(_PRIORITY_ORDER) - 1)]
    return base


def as_catalog() -> dict:
    """La taxonomía para `GET /advisor/taxonomy`: la app del asesor dibuja los selects desde
    aquí en vez de copiar la lista (y con D-008 cerrada se actualiza sola)."""
    return {
        "proposal": True,  # ⚠️ D-008 abierta: la app lo muestra como provisional
        "decision": "D-008",
        "problem_types": [
            {
                "problem_type": str(spec.problem_type),
                "category": str(spec.category),
                "priority": str(spec.priority),
                "when": spec.when,
                "required": [{"name": f.name, "label": f.label} for f in spec.required],
            }
            for spec in TAXONOMY.values()
        ],
        "categories": [str(c) for c in Category],
        "priorities": [str(p) for p in Priority],
        "tags": [str(t) for t in Tag],
    }


# ───────────────────── Reglas por palabras clave (sugerencia, sin IA) ─────────────────────

_WHITESPACE = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Minúsculas, sin tildes, espacios comprimidos. Misma técnica que `agent/heuristics.py`
    (no se importa: el dominio no depende de una integración)."""
    decomposed = unicodedata.normalize("NFKD", text.lower().strip())
    without_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return _WHITESPACE.sub(" ", without_marks)


def _any(*items: str) -> tuple[str, ...]:
    return tuple(normalize(item) for item in items)


# Orden = precedencia. Lo legal y lo que tiene plazo va primero; lo genérico, al final. Cada
# entrada es (regla, tipo, frases); basta que UNA frase aparezca en el texto.
_RULES: tuple[tuple[str, ProblemType, tuple[str, ...]], ...] = (
    # Frase fuerte a propósito: "reclamo" suelto aparece en cualquier queja de pago.
    (
        "libro_de_reclamaciones",
        ProblemType.FORMAL_COMPLAINT,
        _any("libro de reclamaciones", "reclamo formal", "presentar un reclamo",
             "poner un reclamo", "indecopi", "denuncia formal"),
    ),
    (
        "sancion",
        ProblemType.SANCTION_APPEAL,
        _any("sancion", "sancionado", "sancionaron", "me penalizaron", "penalidad",
             "apelar", "apelacion", "me bloquearon por no pagar", "no pude entrar a la sala"),
    ),
    (
        "falla_plataforma",
        ProblemType.PLATFORM_BUG,
        _any("no carga", "no me carga", "se cuelga", "se colgo", "error al pujar",
             "no me deja ofertar", "no me deja pujar", "no entran mis bids", "la sala no",
             "sale error", "me saca de la sala", "pagina caida", "no funciona la sala"),
    ),
    (
        "habilitacion",
        ProblemType.ENABLEMENT_ISSUE,
        _any("habilitacion", "habilitar", "mis documentos", "subi los documentos",
             "documentos rechazados", "rechazaron mis documentos", "ya gane y",
             "gane la oferta y", "plazo para pagar", "vence el plazo"),
    ),
    (
        "devolucion",
        ProblemType.REFUND_REQUEST,
        _any("devolucion", "devuelvan", "devuelvanme", "reembolso", "me devuelven",
             "quiero mi saldo de vuelta", "retirar mi saldo", "liberar mi consignacion"),
    ),
    (
        "pago",
        ProblemType.PAYMENT_ISSUE,
        _any("ya pague", "hice el pago", "pague y no", "no se refleja", "no se ha reflejado",
             "codigo de pago", "cobro duplicado", "me cobraron dos veces", "cobraron de mas",
             "mi pago no aparece"),
    ),
    (
        "deuda",
        ProblemType.DEBT_DISPUTE,
        _any("deuda", "debo", "me sale que debo", "regularizar mi cuenta", "estado de cuenta"),
    ),
    (
        "comprobante",
        ProblemType.RECEIPT_REQUEST,
        _any("boleta", "factura", "comprobante", "recibo de pago"),
    ),
    (
        "visita",
        ProblemType.VISIT_ISSUE,
        _any("agendar una visita", "agendar visita", "quiero visitar", "ver el vehiculo",
             "inspeccion mecanica", "peritaje", "no puedo agendar"),
    ),
    (
        "acceso",
        ProblemType.ACCOUNT_ACCESS,
        _any("no puedo registrarme", "no me deja registrarme", "no puedo entrar a mi cuenta",
             "recuperar mi contraseña", "recuperar contraseña", "no me llega el correo",
             "olvide mi contraseña", "mi usuario no", "persona juridica"),
    ),
    (
        "riesgo_puntos",
        ProblemType.RISK_CATEGORY_DISPUTE,
        _any("riesgo usuario", "mi riesgo", "puntos vmc", "mis puntos", "canje",
             "categoria de riesgo"),
    ),
)


@dataclass(frozen=True, slots=True)
class Suggestion:
    """Lo que proponen las reglas. `rule` en None significa que ninguna decidió y el tipo es
    `OTHER`: se registra igual para poder medir cuántos tickets llegan sin clasificar."""

    problem_type: ProblemType
    rule: str | None
    tags: tuple[Tag, ...]


_TAG_RULES: tuple[tuple[Tag, tuple[str, ...]], ...] = (
    (Tag.EN_VIVO, _any("en vivo", "envivo", "la sala", "sala de subasta", "remate en vivo")),
    (Tag.NEGOCIABLE, _any("negociable", "oferta negociable")),
    (Tag.GANADOR, _any("gane", "ganador", "me adjudicaron", "adjudicado", "ya gane")),
    (
        Tag.PLAZO_CORRIENDO,
        _any("plazo", "vence", "se vence", "ultimo dia", "tengo hasta", "me queda poco tiempo"),
    ),
)


def suggest(text: str) -> Suggestion:
    """Sugiere `problem_type` y etiquetas a partir de lo que escribió el usuario.

    Determinista y gratis: no llama a ningún modelo (no gasta cuota de D-027 ni aparece en
    AIUsage). El asesor confirma o corrige; esa corrección es la medida de si la propuesta de
    D-008 sirve. `RECURRENTE` no se detecta aquí (ver `Tag`).
    """
    normalized = normalize(text)
    tags = tuple(tag for tag, phrases in _TAG_RULES if any(p in normalized for p in phrases))
    for rule, problem_type, phrases in _RULES:
        if any(phrase in normalized for phrase in phrases):
            return Suggestion(problem_type=problem_type, rule=rule, tags=tags)
    return Suggestion(problem_type=ProblemType.OTHER, rule=None, tags=tags)
