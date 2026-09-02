"""Motor de flujos guiados — D-028, mapeo completo en MAPEO.md.

Todo lo que se prueba aqui es puro (funciones y dataclasses de `backend.agent.flows`): sin
red, sin Gemini, sin Pinecone, sin DynamoDB. Quien compone flujo + repositorio + mensajes es
el worker (`workers/ai_worker.py`, fuera de este archivo); aqui solo el motor.

Grupos cubiertos:
  detect_flow_start       dispara solo con las variantes reales del corpus, nunca con FAQ
  extract_offer_type/slot lee "en vivo" / "negociable" del texto libre, o se abstiene
  validate_interaction    barrera de seguridad: el trio exacto (accion, valor, version) o
                           nada — es lo que impide que editar el HTML invente acciones
                           (skill security-guidance)
  quick_replies_metadata  forma exacta de lo que el widget dibuja como botones
  invariantes de FLOWS    ninguna definicion de flujo puede quedar incompleta o romper el
                           contrato de InteractionIn (api/routers/chat.py)
  FlowStep/FlowDefinition los metodos de acceso que usa el worker para leer un paso
"""

import re

import pytest

from backend.agent.flows import (
    FLOWS,
    QUICK_REPLIES,
    FlowStep,
    QuickReply,
    detect_flow_start,
    extract_offer_type,
    extract_slot_value,
    quick_replies_metadata,
    validate_interaction,
)

# El paso de F-PART (MAPEO.md §4.1), usado como paso "vigente" en la mayoria de los tests.
# Las pruebas de invariantes iteran TODO FLOWS — cubren tambien F-CONS/F-LIVE/F-NEGO/F-HAB
# (activados 2026-09-01) y cualquier flujo futuro sin tocar este archivo; sus disparadores y
# extractores propios se prueban en la seccion final.
_OFFER_TYPE_STEP = FLOWS["PARTICIPATION"].step("SELECT_OFFER_TYPE")


# ──────────────────────── detect_flow_start: solo dispara con lo real ────────────────────────


@pytest.mark.parametrize(
    "message",
    [
        "quiero participar",
        "Cómo participo?",
        "deseo participar en una subasta",
        "me interesa participar",
        "quiero pujar",
        "quiero ofertar",
        "quiero bidear",
        "QUIERO PARTICIPAR",  # mayusculas: normalize() debe emparejar igual
        "CÓMO PARTICIPO?",  # mayusculas + tilde a la vez
        "cómo participo",  # tilde en minuscula, sin signo de interrogacion
        "participar en una subasta",  # segunda alternativa del patron (sin verbo "quiero")
    ],
)
def test_detect_flow_start_dispara_con_variantes_reales(message):
    assert detect_flow_start(message) == "PARTICIPATION"


@pytest.mark.parametrize(
    "message",
    [
        "cuánto es la comisión",
        "cómo me registro",
        "quiero un auto",
        "quiero hablar con un asesor",  # otra intencion (ADVISOR) no debe activar el flujo
        "en vivo",  # el valor del slot solo, sin haber disparado el flujo, no lo dispara
    ],
)
def test_detect_flow_start_no_dispara_con_faq_normales(message):
    # Una FAQ plana que active el flujo por error mete estado donde no corresponde
    # (MAPEO.md §4.2: "meter estado ahi es burocracia").
    assert detect_flow_start(message) is None


@pytest.mark.parametrize("message", ["", "   ", None])
def test_detect_flow_start_con_texto_vacio_o_none_no_revienta(message):
    # normalize() recibe `text or ""`: un None no debe propagarse como AttributeError.
    assert detect_flow_start(message) is None


@pytest.mark.parametrize(
    "message",
    [
        "no quiero participar",
        "ya no quiero participar en esto",
        "No deseo participar",
        "tampoco quiero participar",
        "nunca voy a participar",
        # "no puedo participar" es una FAQ legitima de problemas de acceso: debe ir al
        # clasificador/RAG, no a los botones de participacion.
        "no puedo participar en la oferta",
    ],
)
def test_una_negacion_cerca_del_verbo_no_dispara_el_flujo(message):
    """Hallado por esta misma suite (PR #79): "no quiero participar" abria el flujo igual
    que "quiero participar". La negacion apaga el disparador y el mensaje sigue el
    pipeline normal."""
    assert detect_flow_start(message) is None


@pytest.mark.parametrize(
    "message",
    [
        # El "no" lejano no niega la intencion: el disparador debe seguir vivo.
        "no tengo cuenta pero quiero participar",
        "hola, no se mucho de esto, quiero participar",
    ],
)
def test_un_no_lejano_no_apaga_el_disparador(message):
    assert detect_flow_start(message) == "PARTICIPATION"


# ──────────────── extract_offer_type / extract_slot_value: leer el slot del texto ────────────────


@pytest.mark.parametrize(
    "message",
    ["en vivo", "envivo", "EN VIVO", "En Vivo"],
)
def test_extract_offer_type_reconoce_variantes_de_en_vivo(message):
    assert extract_offer_type(message) == "LIVE"


@pytest.mark.parametrize(
    "message",
    ["negociable", "la negociable", "NEGOCIABLE", "Negociable"],
)
def test_extract_offer_type_reconoce_variantes_de_negociable(message):
    assert extract_offer_type(message) == "NEGOTIABLE"


@pytest.mark.parametrize(
    "message",
    [
        "en vivo o negociable",  # ambos: justo el caso donde los botones desambiguan mejor
        "no se todavia",  # ninguno de los dos
        "",
        None,
    ],
)
def test_extract_offer_type_ambiguo_o_ausente_devuelve_none(message):
    assert extract_offer_type(message) is None


def test_extract_slot_value_delega_a_offer_type_en_el_paso_activo():
    # Hoy el unico slot activo es "offer_type" (MAPEO.md): extract_slot_value debe ser un
    # sinonimo exacto de extract_offer_type para ese paso, no una copia divergente.
    assert extract_slot_value(_OFFER_TYPE_STEP, "en vivo") == extract_offer_type("en vivo")
    assert extract_slot_value(_OFFER_TYPE_STEP, "negociable") == "NEGOTIABLE"
    assert extract_slot_value(_OFFER_TYPE_STEP, "no se") is None


def test_extract_slot_value_con_slot_desconocido_devuelve_none():
    """Documenta el limite actual (MAPEO.md: "Hoy todos los pasos activos usan offer_type").

    F-LIVE/F-NEGO/F-HAB estan mapeados con slots "stage"/"topic" pero NO activados: si alguien
    activa uno de esos flujos sin agregar su rama en extract_slot_value, la funcion debe
    abstenerse (None) en vez de devolver un valor erroneo del slot equivocado.
    """
    paso_futuro = FlowStep(
        action_id="SELECT_STAGE", slot="stage", prompt="¿En qué etapa estás?", options=()
    )
    assert extract_slot_value(paso_futuro, "en vivo") is None


# ──────────────── validate_interaction: barrera de seguridad (security-guidance) ────────────────


@pytest.mark.parametrize(
    ("value", "expected"),
    [("LIVE", "LIVE"), ("NEGOTIABLE", "NEGOTIABLE")],
)
def test_validate_interaction_acepta_el_trio_exacto(value, expected):
    interaction = {"action_id": "SELECT_OFFER_TYPE", "value": value, "flow_version": 7}
    assert validate_interaction(_OFFER_TYPE_STEP, interaction, current_version=7) == expected


@pytest.mark.parametrize(
    ("interaction", "razon"),
    [
        (
            {"action_id": "DROP_TABLE", "value": "LIVE", "flow_version": 7},
            "action_id inventado (no es el paso vigente)",
        ),
        (
            {"action_id": "SELECT_OFFER_TYPE", "value": "DROP_TABLE", "flow_version": 7},
            "value fuera del enum cerrado del paso",
        ),
        (
            {"action_id": "SELECT_OFFER_TYPE", "value": "live", "flow_version": 7},
            "value en minusculas: el enum es sensible a mayusculas",
        ),
        (
            {"action_id": "SELECT_OFFER_TYPE", "value": "LIVE", "flow_version": 6},
            "flow_version vieja (boton de un render anterior)",
        ),
        (
            {"action_id": "SELECT_OFFER_TYPE", "value": "LIVE", "flow_version": 8},
            "flow_version futura (no puede existir todavia)",
        ),
        (
            "SELECT_OFFER_TYPE",
            "payload no es un dict (string suelto)",
        ),
        (
            None,
            "payload no es un dict (None)",
        ),
        (
            ["SELECT_OFFER_TYPE", "LIVE", 7],
            "payload no es un dict (lista)",
        ),
        (
            {},
            "dict vacio: faltan los tres campos",
        ),
        (
            {"value": "LIVE", "flow_version": 7},
            "falta action_id",
        ),
        (
            {"action_id": "SELECT_OFFER_TYPE", "flow_version": 7},
            "falta value",
        ),
        (
            {"action_id": "SELECT_OFFER_TYPE", "value": "LIVE"},
            "falta flow_version",
        ),
        (
            {"action_id": "SELECT_OFFER_TYPE", "value": 123, "flow_version": 7},
            "value no es string (entero)",
        ),
        (
            {"action_id": "SELECT_OFFER_TYPE", "value": None, "flow_version": 7},
            "value no es string (None)",
        ),
        (
            {"action_id": "SELECT_OFFER_TYPE", "value": "LIVE", "flow_version": "7"},
            "flow_version no es int (string '7' vs int 7): comparacion estricta de tipo",
        ),
    ],
)
def test_validate_interaction_rechaza_todo_lo_que_no_sea_el_trio_exacto(interaction, razon):
    # Un click invalido no es un error: se degrada a None y el mensaje sigue como texto normal
    # (docstring de flows.py). Aqui solo verificamos el None — el "sigue como texto normal" es
    # responsabilidad del worker, fuera de este archivo.
    assert validate_interaction(_OFFER_TYPE_STEP, interaction, current_version=7) is None, razon


# ──────────────────── quick_replies_metadata: lo que dibuja el widget ────────────────────


def test_quick_replies_metadata_tiene_la_forma_exacta():
    flow = FLOWS["PARTICIPATION"]
    metadata = quick_replies_metadata(flow, _OFFER_TYPE_STEP, version=7)

    assert metadata == {
        "interaction": {
            "type": "QUICK_REPLIES",
            "flow": "PARTICIPATION",
            "action_id": "SELECT_OFFER_TYPE",
            "flow_version": 7,
            "options": [
                {"label": "Oferta En Vivo", "value": "LIVE"},
                {"label": "Oferta Negociable", "value": "NEGOTIABLE"},
            ],
        }
    }
    # El tipo debe venir de la constante del modulo, no de un literal duplicado que pueda
    # divergir del que el widget compara (widget/subastin.js).
    assert metadata["interaction"]["type"] == QUICK_REPLIES


def test_quick_replies_metadata_conserva_el_orden_de_las_opciones():
    # El orden de los botones es UX (cual se ve primero); un dict/set intermedio en la
    # implementacion podria barajarlo sin que ningun test de igualdad de listas lo note si
    # solo se comparara como conjunto.
    paso = FlowStep(
        action_id="X",
        slot="s",
        prompt="p",
        options=(
            QuickReply(label="Tercero", value="C"),
            QuickReply(label="Primero", value="A"),
            QuickReply(label="Segundo", value="B"),
        ),
    )
    metadata = quick_replies_metadata(FLOWS["PARTICIPATION"], paso, version=1)

    assert [o["value"] for o in metadata["interaction"]["options"]] == ["C", "A", "B"]


# ──────────────── Invariantes de definicion: ningun flujo puede quedar a medias ────────────────

# Mismo patron que `InteractionIn.action_id`/`.value` en api/routers/chat.py: si un flujo nuevo
# define un action_id o un value que el API rechazaria, el boton nunca llega a validate_interaction
# porque Pydantic lo tumba antes en /chat/messages.
_WIRE_PATTERN = re.compile(r"^[A-Z0-9_]+$")

# (nombre_de_flujo, step) para TODOS los flujos definidos, activos o no — si mañana se activa
# F-CONS/F-LIVE/F-NEGO/F-HAB (MAPEO.md §4.1) agregando su entrada a FLOWS, estos tests lo cubren
# sin que nadie tenga que acordarse de ampliar este archivo.
_ALL_STEPS = [(nombre, step) for nombre, flujo in FLOWS.items() for step in flujo.steps]
_ALL_STEP_IDS = [f"{nombre}:{step.action_id}" for nombre, step in _ALL_STEPS]


@pytest.mark.parametrize(("nombre_flujo", "step"), _ALL_STEPS, ids=_ALL_STEP_IDS)
def test_todo_option_value_tiene_consulta_canonica(nombre_flujo, step):
    # Una definicion incompleta no falla ruidosamente: silenciosamente manda al RAG una
    # consulta canonica vacia/faltante y degrada la respuesta del paso resuelto a algo pobre.
    for option in step.options:
        assert option.value in step.canonical_queries, (
            f"{nombre_flujo}:{step.action_id} no tiene consulta canonica para {option.value!r}"
        )
        assert step.canonical_queries[option.value].strip(), (
            f"{nombre_flujo}:{step.action_id}: consulta canonica vacia para {option.value!r}"
        )
    # Y a la inversa: una consulta canonica sin option asociada es codigo muerto que nunca se
    # dispara (senal de que un option se borro y su entrada de canonical_queries quedo huerfana).
    valores_con_boton = {option.value for option in step.options}
    assert set(step.canonical_queries) <= valores_con_boton, (
        f"{nombre_flujo}:{step.action_id} tiene consultas canonicas sin boton que las dispare"
    )


@pytest.mark.parametrize(("nombre_flujo", "step"), _ALL_STEPS, ids=_ALL_STEP_IDS)
def test_action_id_y_values_cumplen_el_contrato_del_api(nombre_flujo, step):
    # Si esto falla, el boton que el bot ofrece nunca podria resolverse: /chat/messages
    # rechazaria el POST del click con un 422 antes de que el worker vea nada.
    assert _WIRE_PATTERN.match(step.action_id), (
        f"{nombre_flujo}: action_id {step.action_id!r} no matchea ^[A-Z0-9_]+$ (InteractionIn)"
    )
    for option in step.options:
        assert _WIRE_PATTERN.match(option.value), (
            f"{nombre_flujo}:{step.action_id}: value {option.value!r} no matchea ^[A-Z0-9_]+$"
        )


@pytest.mark.parametrize(("nombre_flujo", "step"), _ALL_STEPS, ids=_ALL_STEP_IDS)
def test_labels_no_vacios_y_en_espanol(nombre_flujo, step):
    for option in step.options:
        assert option.label.strip() == option.label, (
            f"{nombre_flujo}:{step.action_id}: label {option.label!r} con espacios sueltos"
        )
        assert option.label, f"{nombre_flujo}:{step.action_id}: label vacio para {option.value!r}"
        # El label es lo que el usuario LEE y CLICKEA (T7: UI en español); si coincide con el
        # value (dato en ingles) alguien probablemente copio el enum en vez de escribir el
        # texto visible.
        assert option.label != option.value, (
            f"{nombre_flujo}:{step.action_id}: label igual al value ({option.value!r}), "
            "parece un placeholder sin traducir"
        )
        assert any(letra.islower() for letra in option.label), (
            f"{nombre_flujo}:{step.action_id}: label {option.label!r} no parece texto en "
            "español (sin minusculas)"
        )


def test_flows_no_esta_vacio():
    # Guarda contra un refactor que deje FLOWS = {} por accidente: todos los tests de
    # invariantes de arriba pasarian trivialmente (parametrize sobre una lista vacia) sin
    # que nada avise que dejaron de correr.
    assert len(FLOWS) >= 1
    assert all(flujo.steps for flujo in FLOWS.values()), "un flujo sin pasos no sirve de nada"


# ──────────────────── FlowStep.accepts / label_for y FlowDefinition.step ────────────────────


@pytest.mark.parametrize(
    ("value", "aceptado"),
    [
        ("LIVE", True),
        ("NEGOTIABLE", True),
        ("live", False),  # sensible a mayusculas: mismo criterio que el enum de la API
        ("", False),
        ("BOGUS", False),
    ],
)
def test_flow_step_accepts(value, aceptado):
    assert _OFFER_TYPE_STEP.accepts(value) is aceptado


@pytest.mark.parametrize(
    ("value", "label_esperado"),
    [
        ("LIVE", "Oferta En Vivo"),
        ("NEGOTIABLE", "Oferta Negociable"),
        ("BOGUS", None),
        ("", None),
    ],
)
def test_flow_step_label_for(value, label_esperado):
    assert _OFFER_TYPE_STEP.label_for(value) == label_esperado


def test_flow_definition_step_existente_e_inexistente():
    flujo = FLOWS["PARTICIPATION"]

    encontrado = flujo.step("SELECT_OFFER_TYPE")
    assert encontrado is not None
    assert encontrado.action_id == "SELECT_OFFER_TYPE"

    assert flujo.step("NO_EXISTE") is None
    assert flujo.step("") is None


# ────── Los 4 flujos activados el 2026-09-01 (F-CONS, F-LIVE, F-NEGO, F-HAB) ──────
# Las invariantes de la seccion anterior ya los cubren (consultas canonicas completas,
# contrato del API, labels); aqui van sus disparadores y extractores de slot.


@pytest.mark.parametrize(
    ("message", "flujo", "slot"),
    [
        # F-CONS: el verbo disparador debe estar CERCA de "consignar".
        ("quiero consignar", "CONSIGNMENT", None),
        ("¿Cómo y cuánto debo consignar para participar?", "CONSIGNMENT", None),
        ("quiero consignar para una oferta negociable", "CONSIGNMENT", "NEGOTIABLE"),
        # F-HAB: habilitacion mencionada; el tema puede venir en el mismo texto.
        ("me habilitaron para comprar, ¿qué hago?", "ENABLEMENT", None),
        ("me habilitaron, ¿qué documentos debo subir?", "ENABLEMENT", "DOCUMENTS"),
        ("fui habilitado y quiero pagar la comisión", "ENABLEMENT", "COMMISSION"),
        # F-NEGO: exige propuesta/contrapropuesta/negociacion en curso.
        ("el vendedor me mandó una contrapropuesta, ¿qué hago?", "NEGOTIATION_STAGE", "COUNTER"),
        ("¿cómo va mi negociación?", "NEGOTIATION_STAGE", None),
        ("no me aceptaron la propuesta", "NEGOTIATION_STAGE", "REJECTED"),
        # F-LIVE: "en vivo" + duda/etapa, o directamente "gane la oferta".
        ("gané una oferta en vivo, ¿cuáles son los siguientes pasos?", "LIVE_STAGE", "WINNER"),
        ("estoy en una oferta en vivo y no sé qué hacer", "LIVE_STAGE", None),
        ("el proceso en vivo terminó, ¿qué sigue?", "LIVE_STAGE", "FINISHED"),
    ],
)
def test_los_flujos_nuevos_disparan_y_extraen_su_slot(message, flujo, slot):
    assert detect_flow_start(message) == flujo
    step = FLOWS[flujo].steps[0]
    assert extract_slot_value(step, message) == slot


@pytest.mark.parametrize(
    "message",
    [
        # FAQ planas vecinas que NO deben caer en los flujos nuevos (MAPEO.md §4.2).
        "¿cuándo me devuelven la consignación?",  # devolucion, no consignar (F-CONS)
        "¿cómo funciona la oferta Negociable?",  # concepto, no negociacion en curso (F-NEGO)
        "¿qué es el precio base?",  # concepto En Vivo, sin etapa ni duda (F-LIVE)
        "¿cómo se paga la comisión?",  # comision a secas, sin habilitacion (F-HAB)
        "no quiero consignar",  # negacion cerca del verbo (misma regla que participar)
    ],
)
def test_faq_vecinas_no_disparan_los_flujos_nuevos(message):
    assert detect_flow_start(message) is None


def test_consignar_gana_a_participar_cuando_vienen_juntos():
    # "consignar para participar" es F-CONS: el disparador mas especifico manda (orden
    # deliberado de _TRIGGERS). Si F-PART ganara, la respuesta hablaria de participar y no
    # de cuanto consignar, que es lo que se pregunto.
    assert detect_flow_start("quiero consignar para participar en una subasta") == "CONSIGNMENT"


@pytest.mark.parametrize(
    "flujo", ["LIVE_STAGE", "NEGOTIATION_STAGE", "ENABLEMENT", "CONSIGNMENT", "PARTICIPATION"]
)
def test_el_label_de_cada_boton_se_resuelve_igual_que_su_click(flujo):
    """Teclear el texto del boton debe valer lo mismo que clickearlo: si un label no lo
    reconoce su propio extractor, el usuario que escribe en vez de clickear se queda
    esperando botones que ya tenia delante."""
    step = FLOWS[flujo].steps[0]
    for option in step.options:
        assert extract_slot_value(step, option.label) == option.value, option.label


def test_no_me_aceptaron_es_rechazo_no_aceptacion():
    # "no me aceptaron" contiene "aceptaron": sin la regla de negacion, ACCEPTED ganaria y
    # la respuesta hablaria de como pagar una propuesta aceptada — lo contrario de lo que
    # el usuario vive.
    step = FLOWS["NEGOTIATION_STAGE"].steps[0]
    assert extract_slot_value(step, "no me aceptaron la propuesta") == "REJECTED"
    assert extract_slot_value(step, "me aceptaron la propuesta") == "ACCEPTED"


def test_ambiguedad_en_slots_nuevos_devuelve_none():
    # Dos etapas mencionadas a la vez: que desambiguen los botones, no una adivinanza.
    live = FLOWS["LIVE_STAGE"].steps[0]
    assert extract_slot_value(live, "termino la puja y gane") is None
    hab = FLOWS["ENABLEMENT"].steps[0]
    assert extract_slot_value(hab, "ya pagué la comisión y subí los documentos") is None
