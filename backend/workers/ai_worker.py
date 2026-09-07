"""Lambda `worker-ai` — consumidor de SQS `ai-jobs`. Pipeline IA completo (T3/T8, T-24).

Flujo por job (cada paso con su decision al lado):

 1. validar el body con `core.jobs.AIJob` (regla 6 de security-guidance) y cargar conversacion
    y mensaje; un job huerfano se descarta sin reintento.
 2. bot apagado (PENDING_ADVISOR / IN_ATTENTION): el mensaje ya quedo guardado (RF-026);
    si espera asesor, el aviso fijo sale UNA vez por periodo (RF-027 / AC-004). La IA no
    responde (RF-025) y sigue apagada hasta que un asesor tome y cierre el caso (D-007,
    cerrada 2026-08-28: sin expiracion — no se re-enciende sola).
 3. debounce (D-020, cerrada 2026-08-28): el job viajo con DelaySeconds; si el usuario escribio
    algo mas nuevo, este job se salta y el job del ultimo mensaje responde el bloque completo
    de frases seguidas en UNA llamada.
 4. triviales (D-006, cerrada 2026-08-28): saludo/gracias sueltos y mensaje repetido reciben
    respuesta fija sin tocar un modelo; la repeticion se avisa una sola vez.
 5. clasificar (RF-015/016): reglas deterministas primero, tier FAST despues — hoy Gemini
    flash-lite tambien orquesta (TD-008); Haiku sigue siendo el plan B del tier.
 6. rutear: FAQ → RAG en Pinecone + redactor (RF-017/018/020); sin evidencia NO se inventa:
    el bot pregunta si quiere un asesor (D-029). Con evidencia, la respuesta va COMPLETA en
    un turno y lleva en metadata la fuente (chip) y las otras preguntas del mismo articulo
    como botones (D-030, `agent/related.py`); un clic en uno de esos botones vuelve a
    entrar aqui y va al RAG directo, sin clasificador. CATALOG → respuesta fija con enlace
    mientras D-011 siga abierta. ADVISOR → formulario de asesor (autenticado) o invitacion
    a iniciar sesion con boton (anonimo, D-031). OTHER → redireccion fija.
 7. registrar TODA decision en AIUsage (skill llm-cost-optimizer), tambien las gratuitas:
    la proporcion de trafico que no paga tokens es la metrica que justifica D-006 y las reglas.
 8. Slack (RF-028) queda pendiente de D-016; el ticket, del modulo tickets (F5).

Este archivo es la ENTRADA (`handler`, `_process`, `_attend`); las piezas viven en
`workers/ai/` (ver su `__init__`). Timeout largo y memoria propia (distintos de la Lambda
api). visibility_timeout de la cola ≥ 6x el timeout de esta funcion.
"""

import logging

from backend.agent import followups, guardrails, prompts, related, trivial
from backend.agent.classifier import ClassificationResult, classify
from backend.agent.heuristics import classify_by_rules
from backend.agent.intents import Intent
from backend.conversations import service
from backend.conversations.models import (
    Conversation,
    ConversationStatus,
    Message,
    MessageStatus,
    SenderType,
)
from backend.core import llm
from backend.core.jobs import AIJob
from backend.core.observability import configure_logging, content_preview
from backend.workers.ai import guided, state, window
from backend.workers.ai.accounting import record_classification, record_free
from backend.workers.ai.faq import answer_faq
from backend.workers.ai.replies import (
    is_anonymous,
    offer_handoff_form,
    reply_fixed,
    spend_quota_or_reply,
)
from backend.workers.ai.trace import ctx, log_skip

configure_logging()
logger = logging.getLogger(__name__)

# Respuesta fija por tipo de guardrail de entrada (D-024). El texto vive en prompts.py. Un
# tipo nuevo sin respuesta propia cae en la de manipulacion en vez de tumbar el job.
_GUARDRAIL_RESPONSES = {
    guardrails.PROMPT_INJECTION: prompts.GUARDRAIL_INJECTION_RESPONSE,
    guardrails.PRIVACY_REQUEST: prompts.GUARDRAIL_PRIVACY_RESPONSE,
}


def handler(event: dict, context) -> dict:
    failures: list[dict[str, str]] = []
    for record in event["Records"]:
        try:
            _process(record["body"])
        except Exception:  # noqa: BLE001 — el fallo de un mensaje no debe tumbar el batch
            logger.exception("Job IA fallido", extra={"messageId": record.get("messageId")})
            failures.append({"itemIdentifier": record["messageId"]})
    # Formato exacto requerido por SQS partial batch response; si difiere, SQS lo ignora.
    return {"batchItemFailures": failures}


def _process(body: str) -> None:
    job = AIJob.model_validate_json(body)
    conversation = service.get_conversation(job.conversation_id)
    if conversation is None:
        logger.warning("Job para conversacion inexistente", extra={"job": job.conversation_id})
        return
    message = service.get_message(job.conversation_id, job.message_key)
    if message is None or message.sender_type != SenderType.USER:
        return
    if message.status == MessageStatus.PROCESSED:
        logger.debug("ai.job.duplicate", extra=ctx(conversation, message))
        return  # SQS entrega al menos una vez: la re-entrega de un job atendido no repite nada
    logger.debug(
        "ai.job.received",
        extra=ctx(
            conversation, message,
            status=str(conversation.status), bot_enabled=conversation.bot_enabled,
        ),
    )

    try:
        if not conversation.bot_enabled:
            _while_bot_off(conversation)
        else:
            _attend(conversation, message, ip_hash=job.ip_hash)
    except Exception:
        service.set_message_status(message, MessageStatus.FAILED)
        raise
    service.set_message_status(message, MessageStatus.PROCESSED)


def _while_bot_off(conversation: Conversation) -> None:
    """El mensaje ya esta guardado (RF-026); la IA no responde (RF-025). Si el caso espera
    asesor, el aviso de espera sale maximo una vez por periodo (RF-027 / AC-004)."""
    sent = False
    if conversation.status == ConversationStatus.PENDING_ADVISOR:
        sent = service.send_wait_message_once(conversation, prompts.HANDOFF_WAIT_RESPONSE)
    logger.info(
        "ai.bot_off",
        extra=ctx(conversation, status=str(conversation.status), wait_message_sent_now=sent),
    )


def _attend(conversation: Conversation, message: Message, ip_hash: str | None = None) -> None:
    context = service.context_window(conversation.conversation_id)
    block = window.trailing_user_block(context)
    block_keys = [m.message_key for m in block]

    if message.message_key not in block_keys:
        # El hilo ya siguio (hay respuesta posterior): job viejo, nada que responder.
        log_skip(conversation, message, "already_answered")
        return
    if message.message_key != block_keys[-1]:
        # D-020: hay un mensaje mas nuevo; su job respondera el bloque completo.
        log_skip(conversation, message, "newer_message")
        return

    text = "\n".join(m.content for m in block if m.content).strip()
    logger.debug(
        "ai.attend",
        extra=ctx(
            conversation, message,
            user_type=str(conversation.user_type),
            block_messages=len(block), window_messages=len(context),
            text=content_preview(text),
        ),
    )

    # ── D-029: la pregunta "¿te conecto con un asesor?" vale SOLO para este turno ──
    # Se resuelve (o se descarta) ANTES de triviales y continuidad: "ok", "vale" o "gracias"
    # son la respuesta a ESA pregunta, no un cierre de conversacion. Con los triviales
    # primero, un "ok" recibia "¡Con gusto!", el flujo quedaba vivo y un "si" de mas tarde,
    # sobre otro tema, abria el formulario (auditoria 2026-09-06).
    handled, conversation = guided.settle_handoff_confirm(conversation, message, text)
    if handled:
        return

    # ── Continuidad (TD-009): ¿el mensaje solo tiene sentido pegado a lo que pregunto el bot? ──
    # Se decide ANTES de los triviales y de la repeticion porque cambia lo que significan: tras
    # "¿te explico el siguiente paso?", un "ok" no es un "gracias" de cierre, y el tercer "si"
    # seguido no es un mensaje repetido: es el paso 3 de una explicacion que el propio bot
    # pidio continuar (conversaciones reales del 2026-09-03). Reglas sobre texto, sin modelo.
    bot_asked = followups.bot_asked_something(window.last_bot_open_question(context))
    _continuation, followup_rule = followups.is_continuation(text, bot_asked=bot_asked)
    certain_continuation = followup_rule in followups.CERTAIN_CONTINUATIONS

    # ── D-006: triviales, sin llamada IA ──
    kind = trivial.match_trivial(text)
    answering = bot_asked or state.awaiting_slot(conversation)
    if kind == "thanks" and followup_rule == "acuse" and answering:
        # "ok", "listo", "vale" contestan la pregunta abierta del bot (o sus botones en
        # pantalla): la explicacion sigue. "gracias" o "chau" no son acuses y cierran siempre.
        kind = None
    if kind == "greeting":
        reply_fixed(conversation, message, prompts.TRIVIAL_GREETING_RESPONSE, "trivial_greeting")
        return
    if kind == "thanks":
        reply_fixed(conversation, message, prompts.TRIVIAL_THANKS_RESPONSE, "trivial_thanks")
        return
    if kind == "identity":
        reply_fixed(conversation, message, prompts.TRIVIAL_IDENTITY_RESPONSE, "trivial_identity")
        return
    # Un acuse ("si", "listo") o un "y luego?" nunca es "repetido": responde a la ULTIMA
    # pregunta del bot aunque use la misma palabra que la vez anterior. Solo las reglas
    # seguras: un texto corto cualquiera repetido (tambien un intento de manipulacion) sigue
    # recibiendo el aviso de repetido y luego silencio, que es lo que D-024 quiere.
    if not certain_continuation and window.is_repeat(text, context, block_keys):
        if window.already_warned_repeat(context):
            record_free(conversation, message, source="trivial_repeat_silent")
        else:
            reply_fixed(conversation, message, prompts.TRIVIAL_REPEAT_RESPONSE, "trivial_repeat")
        return

    # ── D-024 / RF-052: guardrails de entrada, sin llamada IA ──
    # Van despues de la repeticion a proposito: quien insiste con el mismo intento recibe el
    # aviso de repetido y luego silencio, en vez de una respuesta fija por cada intento.
    verdict = guardrails.check_input(text)
    if verdict is not None:
        # Un intento de manipulacion no deja un flujo colgado esperando datos (MAPEO.md §4.2).
        state.clear_flow_if_active(conversation)
        reply_fixed(
            conversation, message,
            _GUARDRAIL_RESPONSES.get(verdict.kind, prompts.GUARDRAIL_INJECTION_RESPONSE),
            f"guardrail:{verdict.kind}:{verdict.rule}",
        )
        return

    # ── D-030 / D-031: clic en un boton bajo la ultima respuesta con evidencia ──
    # Antes de los flujos y del clasificador: el clic se valida contra el ultimo mensaje del
    # bot, no contra el payload. "Contactar asesor" se reconoce por estructura (ni
    # clasificador ni modelo); una pregunta hermana ya es canonica y va directo al RAG. Y
    # antes de `handle_flow` a proposito: "¿Como participo en una En Vivo?" como boton no
    # debe abrir el flujo de participacion con sus propios botones — ya se eligio que preguntar.
    interaction = window.clicked_interaction(message)
    offered = window.last_bot_metadata(context, block_keys)
    if related.is_advisor_click(interaction, offered):
        logger.info(
            "ai.advisor.click",
            extra=ctx(conversation, message, anonymous=is_anonymous(conversation)),
        )
        offer_handoff_form(conversation, message, reason="advisor_button")
        return
    related_query = related.resolve_click(interaction, offered)
    if related_query is not None:
        if not spend_quota_or_reply(conversation, message, ip_hash):
            return
        logger.info(
            "ai.related.click",
            extra=ctx(conversation, message, query=content_preview(related_query)),
        )
        answer_faq(
            conversation, message, related_query, context, block_keys, source_prefix="related:"
        )
        return

    # ── D-028: flujos guiados con quick replies (MAPEO.md) — reglas y estado, sin IA ──
    # Antes del clasificador a proposito: un click de boton ya trae la intencion estructurada
    # y una respuesta corta ("En Vivo") solo tiene sentido con el estado del flujo.
    if guided.handle_flow(
        conversation, message, text, context, block_keys,
        ip_hash=ip_hash, followup_rule=followup_rule,
    ):
        return

    # ── T-09 / D-027: tope de ejecuciones de IA por actor ──
    # Se decide ANTES de tocar un modelo. Las reglas deterministas siguen vivas con la cuota
    # agotada (no cuestan): "quiero un asesor" — justo lo que promete el mensaje fijo —
    # deriva igual. Solo lo que NECESITA un modelo (clasificar lo ambiguo, redactar una FAQ)
    # recibe la respuesta fija de cuota. En dev todo esta en 0 y este bloque no toca la tabla.
    rules_verdict = classify_by_rules(text)
    needs_model = rules_verdict.intent is None or rules_verdict.intent == Intent.FAQ
    if needs_model and not spend_quota_or_reply(conversation, message, ip_hash):
        return  # cuota agotada: ya salio la respuesta fija, gratis

    # ── RF-015/016: clasificar (reglas → tier FAST; Gemini orquesta por TD-008) ──
    if rules_verdict.intent is None and certain_continuation:
        # "si", "listo", "y luego?": la intencion es seguir con lo que se estaba explicando.
        # Clasificarlo con un modelo no aporta y cuesta una llamada (el redactor ya la hara,
        # D-027). Las reglas de asesor y catalogo corrieron antes: un "quiero un asesor"
        # corto no cae aqui. Lo escrito a mano ("en la web") sigue pasando por el modelo.
        classification = ClassificationResult(
            intent=Intent.FAQ,
            source="rules",
            rule=f"continuation:{followup_rule}",
            usage=llm.empty_usage(),
        )
    else:
        # Las reglas ya corrieron arriba: se le pasan para no evaluarlas dos veces.
        classification = classify(text, window.last_bot_text(context), heuristic=rules_verdict)
    record_classification(conversation, message, classification)
    if classification.intent == Intent.OTHER:
        reply_fixed(conversation, message, prompts.OTHER_INTENT_RESPONSE, "fixed_other",
                    intent=classification.intent)
    elif classification.intent == Intent.CATALOG:
        # Fijo mientras D-011 (contrato HERALD) siga abierta; T-23 lo reemplaza.
        reply_fixed(conversation, message, prompts.CATALOG_FALLBACK_RESPONSE, "fixed_catalog",
                    intent=classification.intent)
    elif classification.intent == Intent.ADVISOR:
        # D-029: el autenticado deriva por formulario (el bot ofrece la tarjeta y sigue
        # atendiendo hasta que la envie); el anonimo recibe la invitacion a iniciar sesion (D-031).
        offer_handoff_form(conversation, message, reason=classification.rule or "advisor_intent")
    else:
        answer_faq(conversation, message, text, context, block_keys)
