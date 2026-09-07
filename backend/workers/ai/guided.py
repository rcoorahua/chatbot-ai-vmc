"""Flujos guiados con quick replies (D-028, mapeo en MAPEO.md) y la confirmacion de asesor
(D-029): el estado vive en la fila de Conversations (`state`), los botones y la pregunta los
publica `replies`, y resolver un paso termina en `faq.answer_faq` con la consulta canonica."""

from backend.agent import flows, followups, prompts
from backend.agent.intents import Intent
from backend.conversations.models import Conversation, Message
from backend.workers.ai import state, window
from backend.workers.ai.faq import answer_faq
from backend.workers.ai.replies import (
    offer_flow_step,
    offer_handoff_form,
    reply_fixed,
    spend_quota_or_reply,
)
from backend.workers.ai.trace import ctx, logger


def settle_handoff_confirm(
    conversation: Conversation, message: Message, text: str
) -> tuple[bool, Conversation]:
    """Resuelve o descarta la pregunta "¿te conecto con un asesor?" (flujo HANDOFF_CONFIRM).

    Devuelve `(atendido, conversacion fresca)`. La pregunta vale para el turno siguiente y
    nada mas: un si/no (boton o escrito) la resuelve; cualquier otra cosa la descarta y el
    mensaje sigue el pipeline como si la pregunta no existiera — incluida la deteccion de
    flujos del corpus, que necesita la fila fresca (sin `active_flow`). Dejarla viva 24 h
    como a un flujo del corpus haria que un "si" de mañana derivara por un tema olvidado.
    Corre ANTES de los triviales (ver `ai_worker._attend`): "ok", "vale" o "gracias" son la
    respuesta a ESA pregunta, no un cierre de conversacion (auditoria 2026-09-06).
    """
    active = state.current_flow(conversation)
    if active is None or active[0].name != flows.HANDOFF_CONFIRM:
        return False, conversation
    _definition, step, vigente = active
    value = _slot_value(step, conversation, message, text)
    state.clear_flow_if_active(conversation)
    fresh = state.refreshed(conversation)
    if value is None or not vigente:
        return False, fresh
    _resolve_handoff_confirm(fresh, message, value)
    return True, fresh


def _slot_value(
    step: flows.FlowStep, conversation: Conversation, message: Message, text: str
) -> str | None:
    """El valor que resuelve el paso: el boton pulsado (validado contra el paso y la version
    vigentes) o, si no hubo clic valido, lo que el usuario escribio."""
    interaction = window.clicked_interaction(message)
    value = (
        flows.validate_interaction(step, interaction, current_version=conversation.flow_version)
        if interaction is not None
        else None
    )
    return value if value is not None else flows.extract_slot_value(step, text)


def handle_flow(
    conversation: Conversation,
    message: Message,
    text: str,
    context: list[Message],
    block_keys: list[str],
    *,
    ip_hash: str | None = None,
    followup_rule: str | None = None,
) -> bool:
    """True si el flujo guiado del CORPUS atendio el mensaje (D-028). El orden importa:

    1. flujo activo + click valido o texto que resuelve el slot → responder con la consulta
       canonica y cerrar el flujo;
    2. flujo activo + texto que NO resuelve → interrupcion FAQ: el flujo queda esperando y el
       mensaje sigue el pipeline normal (False);
    3. sin flujo + disparador con el dato ya en el texto ("participar en una En Vivo") →
       respuesta directa, sin botones ni estado;
    4. sin flujo + disparador sin dato → persistir el paso y ofrecer los botones (sin IA).

    La confirmacion de asesor (HANDOFF_CONFIRM) no llega aqui: `_attend` la resuelve o
    descarta antes (`settle_handoff_confirm`) y pasa la fila fresca.
    """
    active = state.current_flow(conversation)
    if active is not None:
        definition, step, vigente = active
        if not vigente:
            # Vencio (24 h): se limpia y este mensaje se atiende como cualquier otro —
            # incluida la deteccion de flujos de abajo, que necesita la fila fresca.
            state.clear_flow_if_active(conversation)
            conversation = state.refreshed(conversation)
        else:
            value = _slot_value(step, conversation, message, text)
            if value is None:
                if followup_rule in followups.CERTAIN_CONTINUATIONS:
                    # "si", "listo", "¿y ahora?" con los botones en pantalla: quiere seguir
                    # pero no eligio. Se repiten los botones (gratis) en vez de mandar el
                    # acuse al indice, donde no recupera nada y terminaba en "no tengo ese
                    # dato, ¿quieres un asesor?" (bateria real del 2026-09-03).
                    offer_flow_step(conversation, message, definition, step)
                    return True
                return False  # interrupcion: el flujo espera hasta resolverse o vencer
            # T-09/D-027: resolver el paso llama al redactor (pagado). Con la cuota agotada
            # el flujo QUEDA esperando: al renovarse, "en vivo" lo resuelve igual.
            if not spend_quota_or_reply(conversation, message, ip_hash):
                return True
            state.clear_flow_if_active(conversation)
            _answer_flow_step(conversation, message, definition, step, value, context, block_keys)
            return True

    flow_name = flows.detect_flow_start(text)
    if flow_name is None:
        return False
    definition = flows.FLOWS[flow_name]
    step = definition.steps[0]
    direct = flows.extract_slot_value(step, text)
    if direct is not None:
        if not spend_quota_or_reply(conversation, message, ip_hash):
            return True
        _answer_flow_step(conversation, message, definition, step, direct, context, block_keys)
        return True
    # Ofrecer los botones no llama a ningun modelo: no gasta cuota ni se bloquea por ella.
    offer_flow_step(conversation, message, definition, step)
    return True


def _resolve_handoff_confirm(conversation: Conversation, message: Message, value: str) -> None:
    """El usuario contesto la pregunta de "¿te conecto con un asesor?". Gratis en los dos
    caminos: publicar el formulario o despedirse no cuesta ninguna llamada a modelo."""
    logger.info("ai.handoff.confirm", extra=ctx(conversation, message, value=value))
    if value == "YES":
        offer_handoff_form(conversation, message, reason="faq_no_evidence")
        return
    reply_fixed(
        conversation, message, prompts.HANDOFF_DECLINED_RESPONSE, "handoff_declined",
        intent=Intent.ADVISOR,
    )


def _answer_flow_step(
    conversation: Conversation,
    message: Message,
    definition: flows.FlowDefinition,
    step: flows.FlowStep,
    value: str,
    context: list[Message],
    block_keys: list[str],
) -> None:
    """Paso resuelto: RAG + redactor con la consulta canonica del valor elegido."""
    query = step.canonical_queries.get(value)
    if not query:
        # Definicion incompleta (enum acepta un valor sin consulta): mejor el pipeline comun
        # que un KeyError que deje el mensaje sin respuesta.
        logger.warning(
            "flow.sin_consulta_canonica",
            extra={"flow": definition.name, "step": step.action_id, "value": value},
        )
        query = f"{step.prompt} {step.label_for(value) or value}"
    logger.info(
        "ai.flow.resolved",
        extra=ctx(conversation, message, flow=definition.name, step=step.action_id, value=value),
    )
    answer_faq(
        conversation, message, query, context, block_keys,
        source_prefix=f"flow:{definition.name}:{value}:",
    )
