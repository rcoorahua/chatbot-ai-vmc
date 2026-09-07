"""Toda respuesta del bot sale por aqui: fijas (triviales, guardrails, OTHER, catalogo),
la invitacion a iniciar sesion del anonimo (D-031), el formulario de asesor (D-029), los
botones de un paso de flujo (D-028), la pregunta "¿te conecto con un asesor?" y la cuota
agotada (D-027). Cada una deja su fila gratuita en AIUsage (`accounting.record_free`).
"""

from datetime import timedelta

from backend.agent import flows, prompts, quota
from backend.agent.intents import Intent
from backend.conversations import forms, service
from backend.conversations.models import Conversation, Message, UserType
from backend.core.clock import to_iso, utc_now
from backend.core.config import get_settings
from backend.core.metadata import InteractionType, link, with_interaction
from backend.workers.ai import state
from backend.workers.ai.accounting import record_free
from backend.workers.ai.trace import ctx, log_skip, logger


def is_anonymous(conversation: Conversation) -> bool:
    return conversation.user_type == UserType.ANONYMOUS


def bot_says(conversation: Conversation, text: str, *, metadata: dict | None = None) -> None:
    """Toda respuesta del bot sale por aqui: arrastra el TTL de la conversacion anonima
    (D-029) para que sus mensajes caduquen con ella."""
    service.post_bot_message(
        conversation.conversation_id, text, metadata=metadata, expires_at=conversation.expires_at
    )


def reply_fixed(
    conversation: Conversation,
    message: Message,
    text: str,
    source: str,
    *,
    intent: Intent | None = None,
) -> None:
    bot_says(conversation, text)
    record_free(conversation, message, source=source, intent=intent)


def reply_login(
    conversation: Conversation,
    message: Message,
    text: str,
    *,
    source: str,
    intent: Intent | None,
) -> None:
    """D-031: la salida fija del anonimo hacia el login de VMC (pidio asesor, dijo que si a
    la pregunta de asesor, o agoto su cuota). El enlace viaja como boton
    (`interaction.type = LINKS`, el widget lo dibuja bajo la burbuja), nunca dentro del
    texto (D-025/D-030). Gratis."""
    links = with_interaction(
        InteractionType.LINKS,
        options=[link(prompts.LOGIN_LINK_LABEL, get_settings().vmc_login_url)],
    )
    bot_says(conversation, text, metadata=links)
    record_free(conversation, message, source=source, intent=intent)


def offer_handoff_form(conversation: Conversation, message: Message, *, reason: str) -> None:
    """D-029: pedir asesor ya no deriva de inmediato. El bot ofrece la TARJETA de formulario
    (asunto y detalle; correo si el JWT no lo trajo) y la derivacion la hace
    `POST /chat/.../handoff` cuando el usuario la envia. Hasta entonces el bot sigue
    encendido: quien ignora la tarjeta puede seguir preguntando. Al anonimo no se le ofrece
    nada que llenar (D-031): se le pide iniciar sesion, con el boton al login de VMC."""
    # Con un humano en camino, ningun flujo guiado sigue esperando datos (MAPEO.md §4.2).
    state.clear_flow_if_active(conversation)
    if is_anonymous(conversation):
        reply_login(
            conversation, message, prompts.ANON_LOGIN_RESPONSE,
            source=f"login:{reason}", intent=Intent.ADVISOR,
        )
        return
    bot_says(
        conversation,
        prompts.HANDOFF_OFFER_RESPONSE,
        metadata=forms.handoff_form_spec(needs_email=not conversation.user_email),
    )
    logger.info(
        "ai.handoff.offer",
        extra=ctx(conversation, message, reason=reason, intent=str(Intent.ADVISOR)),
    )
    record_free(
        conversation, message, source=f"handoff_offer:{reason}", intent=Intent.ADVISOR,
        handoff=True,
    )


def offer_flow_step(
    conversation: Conversation,
    message: Message,
    definition: flows.FlowDefinition,
    step: flows.FlowStep,
    *,
    text: str | None = None,
) -> None:
    """Persiste el paso y publica la pregunta con quick replies. Cero llamadas IA.

    `text` reemplaza al del paso cuando quien ofrece ya tiene su propio mensaje (la
    confirmacion de asesor lo usa para no partir "no tengo el dato" y "¿quieres un asesor?"
    en dos burbujas seguidas del bot).
    """
    expires_at = to_iso(utc_now() + timedelta(hours=flows.FLOW_TTL_HOURS))
    version = service.start_flow(
        conversation, flow=definition.name, step=step.action_id, expires_at=expires_at
    )
    if version is None:
        # Otro job gano la transicion (rafaga D-020): ese publico los botones, aqui silencio.
        log_skip(conversation, message, "flow_race")
        return
    bot_says(
        conversation,
        text or step.prompt,
        metadata=flows.quick_replies_metadata(definition, step, version),
    )
    record_free(conversation, message, source=f"flow:{definition.name}:offered")


def offer_handoff_confirm(
    conversation: Conversation, message: Message, *, text: str | None = None
) -> None:
    """Sin evidencia (RF-018): se reconoce el limite y se PREGUNTA si quiere un asesor.
    `text` reemplaza al mensaje de "no tengo ese dato" cuando el motivo es otro (el modelo
    no respondio: `prompts.MODEL_UNAVAILABLE_CONFIRM_RESPONSE`).

    Revision de D-029 (2026-09-02, Aaron): antes esto publicaba el formulario de una, y el
    usuario terminaba con una tarjeta de datos delante sin haber pedido nada. Ahora sale la
    pregunta con botones si/no y el formulario espera a que conteste que si.

    Ojo con lo que NO cambia: cuando el usuario PIDE un asesor (intent ADVISOR), el formulario
    sigue saliendo directo — volver a preguntarle "¿quieres un asesor?" a quien acaba de
    pedirlo es un turno de mas por nada.

    El anonimo recibe la MISMA pregunta (D-031: el sistema no lo distingue aqui); lo que
    cambia es la respuesta a su "si": iniciar sesion en vez del formulario
    (`offer_handoff_form`).
    """
    # Se RELEE la conversacion: si en este mismo job se limpio un flujo guiado (un paso que se
    # resolvio y no trajo evidencia), `conversation.flow_version` quedo viejo y la transicion
    # fallaria por condicion — dejando al usuario sin pregunta y sin respuesta. Lo encontro
    # tests/test_ai_worker_flows.py::...sin_evidencia_al_resolver...
    definition = flows.FLOWS[flows.HANDOFF_CONFIRM]
    offer_flow_step(
        state.refreshed(conversation), message, definition, definition.steps[0],
        text=text or prompts.FAQ_NO_EVIDENCE_CONFIRM_RESPONSE,
    )


# ───────────────────────── Cuota de IA (T-09 / D-027, rev. 2026-09-01) ─────────────────────────


def spend_quota_or_reply(
    conversation: Conversation, message: Message, ip_hash: str | None
) -> bool:
    """True = hay cuota (y queda gastada 1 ejecucion); False = agotada y ya se respondio el
    mensaje fijo. Con los topes en 0 (dev) siempre True sin tocar la tabla."""
    anonymous = is_anonymous(conversation)
    if not quota.enabled(anonymous=anonymous):
        return True
    actor = {
        "anonymous": anonymous,
        "user_id": conversation.user_id,
        "conversation_id": conversation.conversation_id,
        "ip_hash": ip_hash,
    }
    if quota.exhausted(**actor):
        _reply_quota(conversation, message)
        return False
    quota.spend(**actor)
    return True


def _reply_quota(conversation: Conversation, message: Message) -> None:
    """Respuesta fija de cuota agotada (gratis): al anonimo lo orienta a iniciar sesion, con
    el boton (duplica su cuota y habilita el asesor, D-027/D-031); al autenticado, a pedir un
    asesor — ruta que sale por reglas y funciona sin modelo."""
    if is_anonymous(conversation):
        reply_login(
            conversation, message, prompts.QUOTA_EXHAUSTED_ANON_RESPONSE,
            source="quota:exhausted", intent=None,
        )
        return
    reply_fixed(conversation, message, prompts.QUOTA_EXHAUSTED_AUTH_RESPONSE, "quota:exhausted")
