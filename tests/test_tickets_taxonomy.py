"""Taxonomía de tickets (`backend/tickets/taxonomy.py`) — ⚠️ propuesta, D-008 abierta.

Criterios (puros, sin DynamoDB):
  AC-X1  cada `problem_type` del corpus (MAPEO.md §8) tiene categoría, prioridad y datos
         mínimos, y un tipo desconocido cae en OTHER en vez de reventar
  AC-X2  las reglas sugieren el tipo a partir de lo que escribe el usuario, en el orden de
         precedencia acordado (lo legal y lo que corre primero)
  AC-X3  ante la duda la regla NO decide: "reclamo" suelto no es un reclamo formal, y lo que
         no calza queda en OTHER con `rule=None`
  AC-X4  las etiquetas salen del texto y una etiqueta que corre sube la prioridad un escalón,
         sin pasarse de HIGH
  AC-X5  `missing_data` mengua conforme el asesor registra datos (RF-024)
  AC-X6  el catálogo que consume la app del asesor viaja marcado como propuesta

Estas pruebas fijan la PROPUESTA, no la decisión: cuando Silvana + Julio cierren D-008 con
otra lista, este archivo y `taxonomy.py` cambian juntos.
"""

import pytest

from backend.tickets import taxonomy
from backend.tickets.taxonomy import Category, Priority, ProblemType, Tag

# ───────────────────── AC-X1: la tabla de MAPEO.md §8, completa ─────────────────────


def test_los_doce_tipos_del_corpus_estan_definidos():
    assert set(taxonomy.TAXONOMY) == set(ProblemType)
    assert len(ProblemType) == 12


@pytest.mark.parametrize("problem_type", list(ProblemType))
def test_cada_tipo_tiene_categoria_prioridad_y_explicacion(problem_type):
    spec = taxonomy.spec_for(problem_type)
    assert spec.category in Category
    assert spec.priority in Priority
    assert spec.when, "el asesor elige entre 12 códigos en inglés: necesita el cuándo"
    assert all(f.name and f.label for f in spec.required)


def test_un_tipo_desconocido_cae_en_other_sin_reventar():
    """Una fila vieja o D-008 cerrada con otra lista no puede dejar un ticket inatendible."""
    assert taxonomy.spec_for("TIPO_QUE_NO_EXISTE").problem_type == ProblemType.OTHER
    assert taxonomy.missing_data("TIPO_QUE_NO_EXISTE", None) == []


def test_las_prioridades_siguen_el_mapeo():
    esperado = {
        ProblemType.PAYMENT_ISSUE: Priority.HIGH,
        ProblemType.REFUND_REQUEST: Priority.HIGH,
        ProblemType.SANCTION_APPEAL: Priority.HIGH,
        ProblemType.ENABLEMENT_ISSUE: Priority.HIGH,
        ProblemType.FORMAL_COMPLAINT: Priority.HIGH,
        ProblemType.DEBT_DISPUTE: Priority.MEDIUM,
        ProblemType.RECEIPT_REQUEST: Priority.LOW,
        # MAPEO.md: "Alta durante un proceso En Vivo" — base media que sube con la etiqueta.
        ProblemType.PLATFORM_BUG: Priority.MEDIUM,
    }
    for problem_type, priority in esperado.items():
        assert taxonomy.spec_for(problem_type).priority == priority, problem_type


# ───────────────────── AC-X2: las reglas sugieren el tipo ─────────────────────


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("Ya pagué y no se refleja en mi cuenta", ProblemType.PAYMENT_ISSUE),
        ("me cobraron dos veces el fee", ProblemType.PAYMENT_ISSUE),
        ("Devuélvanme mi saldo en dólares por favor", ProblemType.REFUND_REQUEST),
        ("quiero el reembolso de mi consignación", ProblemType.REFUND_REQUEST),
        ("Tengo una deuda que no reconozco", ProblemType.DEBT_DISPUTE),
        ("no pude entrar a la sala por mi internet, ¿me sancionan?", ProblemType.SANCTION_APPEAL),
        ("quiero apelar la penalidad que me pusieron", ProblemType.SANCTION_APPEAL),
        ("subí mis documentos y nadie me responde", ProblemType.ENABLEMENT_ISSUE),
        ("rechazaron mis documentos de habilitación", ProblemType.ENABLEMENT_ISSUE),
        ("necesito mi boleta del proceso que terminó", ProblemType.RECEIPT_REQUEST),
        ("no puedo registrarme, el formulario me rechaza", ProblemType.ACCOUNT_ACCESS),
        ("no me llega el correo para recuperar mi contraseña", ProblemType.ACCOUNT_ACCESS),
        ("¿por qué mi Riesgo Usuario es Alto?", ProblemType.RISK_CATEGORY_DISPUTE),
        ("perdí mis Puntos VMC y no sé por qué", ProblemType.RISK_CATEGORY_DISPUTE),
        ("quiero agendar una visita para ver el auto", ProblemType.VISIT_ISSUE),
        ("necesito una inspección mecánica", ProblemType.VISIT_ISSUE),
        ("la sala no carga y no me deja pujar", ProblemType.PLATFORM_BUG),
        ("ya van 3 veces que sale error al ofertar", ProblemType.PLATFORM_BUG),
        ("quiero presentar un reclamo formal", ProblemType.FORMAL_COMPLAINT),
        ("voy a ir a Indecopi", ProblemType.FORMAL_COMPLAINT),
    ],
)
def test_las_reglas_sugieren_el_tipo_del_corpus(texto, esperado):
    sugerencia = taxonomy.suggest(texto)
    assert sugerencia.problem_type == esperado, sugerencia
    assert sugerencia.rule, "una regla que decide tiene que decir cuál fue"


def test_lo_legal_y_lo_que_corre_gana_al_motivo_generico():
    """Precedencia: quien no pudo entrar a la sala apela una sanción, no reporta un bug — es
    lo que MAPEO.md §8 describe y lo que decide qué área lo atiende."""
    assert (
        taxonomy.suggest("no pude entrar a la sala, la app no cargaba").problem_type
        == ProblemType.SANCTION_APPEAL
    )


# ───────────────────── AC-X3: ante la duda, la regla no decide ─────────────────────


def test_la_palabra_reclamo_suelta_no_es_un_reclamo_formal():
    """`FORMAL_COMPLAINT` tiene plazo legal: abrirlo por una queja cualquiera manda a
    Compliance algo que era de Billing. Exige la frase fuerte."""
    sugerencia = taxonomy.suggest("quiero hacer un reclamo, ya pagué y no se refleja")
    assert sugerencia.problem_type == ProblemType.PAYMENT_ISSUE


def test_lo_que_no_calza_queda_en_other_y_se_puede_medir():
    sugerencia = taxonomy.suggest("hola, tengo una consulta sobre algo distinto")
    assert sugerencia.problem_type == ProblemType.OTHER
    assert sugerencia.rule is None, "sin regla: es lo que mide cuánto NO clasifica la propuesta"


def test_las_tildes_y_las_mayusculas_no_cambian_la_regla():
    con = taxonomy.suggest("DEVOLUCIÓN de mi saldo")
    sin = taxonomy.suggest("devolucion de mi saldo")
    assert con.problem_type == sin.problem_type == ProblemType.REFUND_REQUEST


# ───────────────────── AC-X4: etiquetas y prioridad ─────────────────────


def test_las_etiquetas_salen_del_texto():
    sugerencia = taxonomy.suggest("gané una oferta en vivo y el plazo se vence mañana")
    assert set(sugerencia.tags) == {Tag.EN_VIVO, Tag.GANADOR, Tag.PLAZO_CORRIENDO}


def test_recurrente_no_se_detecta_sola():
    """La pone el asesor: detectarla necesitaría un índice de Tickets por usuario que hoy no
    existe (agregar un GSI es decisión de modelo, PLAN.md §4)."""
    assert Tag.RECURRENTE not in taxonomy.suggest("otra vez el mismo problema de siempre").tags


def test_una_etiqueta_que_corre_sube_la_prioridad_un_escalon():
    assert taxonomy.resolve_priority(ProblemType.PLATFORM_BUG, []) == Priority.MEDIUM
    assert taxonomy.resolve_priority(ProblemType.PLATFORM_BUG, [Tag.EN_VIVO]) == Priority.HIGH
    assert (
        taxonomy.resolve_priority(ProblemType.RECEIPT_REQUEST, [Tag.PLAZO_CORRIENDO])
        == Priority.MEDIUM
    )


def test_la_prioridad_no_se_pasa_de_alta_ni_la_sube_una_etiqueta_cualquiera():
    assert taxonomy.resolve_priority(ProblemType.PAYMENT_ISSUE, [Tag.EN_VIVO]) == Priority.HIGH
    assert taxonomy.resolve_priority(ProblemType.PLATFORM_BUG, [Tag.NEGOCIABLE]) == Priority.MEDIUM


# ───────────────────── AC-X5: datos mínimos (RF-024) ─────────────────────


def test_los_datos_minimos_menguan_conforme_el_asesor_los_registra():
    faltan = taxonomy.missing_data(ProblemType.PAYMENT_ISSUE, None)
    assert faltan == ["offer_id", "payment_method", "payment_date", "amount"]

    parcial = taxonomy.missing_data(ProblemType.PAYMENT_ISSUE, {"offer_id": "OF-123"})
    assert parcial == ["payment_method", "payment_date", "amount"]

    vacio = taxonomy.missing_data(ProblemType.PAYMENT_ISSUE, {"offer_id": "   "})
    assert vacio == faltan, "un dato en blanco no es un dato registrado"


def test_un_tipo_sin_datos_minimos_no_pide_nada():
    assert taxonomy.missing_data(ProblemType.RISK_CATEGORY_DISPUTE, None) == []


# ───────────────────── AC-X6: el catálogo del asesor ─────────────────────


def test_el_catalogo_viaja_marcado_como_propuesta():
    catalogo = taxonomy.as_catalog()
    assert catalogo["proposal"] is True and catalogo["decision"] == "D-008"
    assert len(catalogo["problem_types"]) == len(ProblemType)
    payment = next(
        t for t in catalogo["problem_types"] if t["problem_type"] == "PAYMENT_ISSUE"
    )
    assert payment["category"] == "BILLING" and payment["priority"] == "HIGH"
    assert {"name": "amount", "label": "Monto"} in payment["required"]
    assert "RECURRENTE" in catalogo["tags"] and "GENERAL" in catalogo["categories"]
