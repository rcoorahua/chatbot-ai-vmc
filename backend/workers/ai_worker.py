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
    autenticado deriva (AC-002), anonimo recibe invitacion a iniciar sesion (D-002).
    CATALOG → respuesta fija con enlace mientras D-011 siga abierta. ADVISOR → handoff
    (anonimo: invitacion a login). OTHER → redireccion fija.
 7. registrar TODA decision en AIUsage (skill llm-cost-optimizer), tambien las gratuitas:
    la proporcion de trafico que no paga tokens es la metrica que justifica D-006 y las reglas.
 8. Slack (RF-028) queda pendiente de D-016; el ticket, del modulo tickets (F5).

Timeout largo y memoria propia (distintos de la Lambda api). visibility_timeout de la cola ≥ 6x
el timeout de esta funcion.
"""

import logging

from backend.agent import guardrails, prompts, rag, trivial, usage, writer
from backend.agent.classifier import ClassificationResult, classify
from backend.agent.intents import Intent
from backend.conversations import repository, service
from backend.conversations.models import (
    Conversation,
    ConversationStatus,
    Message,
    MessageStatus,
    SenderType,
    UserType,
)
from backend.core import llm
from backend.core.clock import minutes_ago_iso
from backend.core.config import get_settings
from backend.core.jobs import AIJob
from backend.core.observability import configure_logging, content_preview

configure_logging()
logger = logging.getLogger(__name__)

_GOOGLE = "GOOGLE"

# Respuesta fija por tipo de guardrail de entrada (D-024). El texto vive en prompts.py.
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
    conversation = repository.get_conversation(job.conversation_id)
    if conversation is None:
        logger.warning("Job para conversacion inexistente", extra={"job": job.conversation_id})
        return
    message = repository.get_message(job.conversation_id, job.message_key)
    if message is None or message.sender_type != SenderType.USER:
        return
    if message.status == MessageStatus.PROCESSED:
        logger.debug(
            "ai.job.duplicate",
            extra={"conversation_id": job.conversation_id, "message_id": job.message_id},
        )
        return  # SQS entrega al menos una vez: la re-entrega de un job atendido no repite nada
    logger.debug(
        "ai.job.received",
        extra={
            "conversation_id": job.conversation_id,
            "message_id": job.message_id,
            "status": str(conversation.status),
            "bot_enabled": conversation.bot_enabled,
        },
    )

    try:
        if not conversation.bot_enabled:
            _while_bot_off(conversation)
        else:
            _attend(conversation, message)
    except Exception:
        repository.update_message_status(
            job.conversation_id, job.message_key, MessageStatus.FAILED
        )
        raise
    repository.update_message_status(job.conversation_id, job.message_key, MessageStatus.PROCESSED)


def _while_bot_off(conversation: Conversation) -> None:
    """El mensaje ya esta guardado (RF-026); la IA no responde (RF-025). Si el caso espera
    asesor, el aviso de espera sale maximo una vez por periodo (RF-027 / AC-004)."""
    sent = False
    if conversation.status == ConversationStatus.PENDING_ADVISOR:
        sent = service.send_wait_message_once(conversation, prompts.HANDOFF_WAIT_RESPONSE)
    logger.info(
        "ai.bot_off",
        extra={
            "conversation_id": conversation.conversation_id,
            "status": str(conversation.status),
            "wait_message_sent_now": sent,
        },
    )


def _attend(conversation: Conversation, message: Message) -> None:
    window = service.context_window(conversation.conversation_id)
    block = _trailing_user_block(window)
    block_keys = [m.message_key for m in block]

    if message.message_key not in block_keys:
        # El hilo ya siguio (hay respuesta posterior): job viejo, nada que responder.
        _log_skip(conversation, message, "already_answered")
        return
    if message.message_key != block_keys[-1]:
        # D-020: hay un mensaje mas nuevo; su job respondera el bloque completo.
        _log_skip(conversation, message, "newer_message")
        return

    text = "\n".join(m.content for m in block if m.content).strip()
    if not text:
        return
    logger.debug(
        "ai.attend",
        extra={
            "conversation_id": conversation.conversation_id,
            "message_id": message.message_id,
            "user_type": str(conversation.user_type),
            "block_messages": len(block),
            "window_messages": len(window),
            "text": content_preview(text),
        },
    )

    # ── D-006: triviales, sin llamada IA ──
    kind = trivial.match_trivial(text)
    if kind == "greeting":
        _reply_fixed(conversation, message, prompts.TRIVIAL_GREETING_RESPONSE, "trivial_greeting")
        return
    if kind == "thanks":
        _reply_fixed(conversation, message, prompts.TRIVIAL_THANKS_RESPONSE, "trivial_thanks")
        return
    if kind == "identity":
        _reply_fixed(conversation, message, prompts.TRIVIAL_IDENTITY_RESPONSE, "trivial_identity")
        return
    if _is_repeat(text, window, block_keys):
        if _already_warned_repeat(window):
            _record_free(conversation, message, source="trivial_repeat_silent")
        else:
            _reply_fixed(conversation, message, prompts.TRIVIAL_REPEAT_RESPONSE, "trivial_repeat")
        return

    # ── D-024 / RF-052: guardrails de entrada, sin llamada IA ──
    # Van despues de la repeticion a proposito: quien insiste con el mismo intento recibe el
    # aviso de repetido y luego silencio, en vez de una respuesta fija por cada intento.
    verdict = guardrails.check_input(text)
    if verdict is not None:
        _reply_fixed(
            conversation, message, _GUARDRAIL_RESPONSES[verdict.kind],
            f"guardrail:{verdict.kind}:{verdict.rule}",
        )
        return

    # ── RF-015/016: clasificar (reglas → tier FAST; Gemini orquesta por TD-008) ──
    classification = classify(text, _last_bot_message(window))
    _record_classification(conversation, message, classification)

    anonymous = conversation.user_type == UserType.ANONYMOUS
    if classification.intent == Intent.OTHER:
        _reply_fixed(conversation, message, prompts.OTHER_INTENT_RESPONSE, "fixed_other",
                     intent=classification.intent)
    elif classification.intent == Intent.CATALOG:
        # Fijo mientras D-011 (contrato HERALD) siga abierta; T-23 lo reemplaza.
        _reply_fixed(conversation, message, prompts.CATALOG_FALLBACK_RESPONSE, "fixed_catalog",
                     intent=classification.intent)
    elif classification.intent == Intent.ADVISOR:
        if anonymous:
            # D-002: el anonimo no deriva; se le invita a iniciar sesion.
            _reply_fixed(conversation, message, prompts.ANONYMOUS_ADVISOR_RESPONSE,
                         "fixed_anonymous_advisor", intent=classification.intent)
        else:
            _handoff(conversation, message, reason=classification.rule or "advisor_intent",
                     intent=classification.intent, response=prompts.HANDOFF_STARTED_RESPONSE)
    else:
        _answer_faq(conversation, message, text, window, block_keys, anonymous)


# ─────────────────────────────────── Rutas de respuesta ───────────────────────────────────


def _answer_faq(
    conversation: Conversation,
    message: Message,
    text: str,
    window: list[Message],
    block_keys: list[str],
    anonymous: bool,
) -> None:
    """FAQ con RAG (RF-017): recuperar, redactar con evidencia, y sin evidencia derivar en vez
    de inventar (RF-018 / AC-002)."""
    retrieved = rag.retrieve(text)
    fragments = retrieved.relevant
    logger.debug(
        "ai.rag",
        extra={
            "conversation_id": conversation.conversation_id,
            "message_id": message.message_id,
            "results": len(fragments),
            "discarded": len(retrieved.discarded),
            "threshold": retrieved.threshold,
            "best_score": round(
                max((f.score for f in retrieved.all_fragments), default=0.0), 3
            ),
            "topics": [f.topic for f in fragments][:5],
        },
    )
    result = writer.write_answer(
        text,
        [fragment.as_context() for fragment in fragments],
        history=_history(window, block_keys),
    )
    if result.guardrail:
        # El modelo respondio pero se salio de la evidencia (cifra o enlace ajenos, fuga del
        # prompt): se registra aparte de "sin evidencia" porque el arreglo es distinto (prompt
        # o corpus, no umbral del RAG).
        source = f"guardrail:{result.guardrail}"
    else:
        source = "model" if result.model else "fallback"
    usage.record_execution(
        conversation_id=conversation.conversation_id,
        message_id=message.message_id,
        execution_type=usage.RESPONSE,
        intent=str(Intent.FAQ),
        source=source,
        provider=_GOOGLE if result.model else usage.NO_PROVIDER,
        model=result.model,
        usage=result.usage,
        estimated_cost_usd=_cost(llm.ModelTier.ANSWER, result.model, result.usage),
        latency_ms=result.latency_ms,
        rag_used=bool(fragments),
        rag_results_count=len(fragments),
        # TODOS los hits, tambien los que no superaron el umbral: cuando la respuesta cae en
        # "sin evidencia", la consola de dev necesita ver que trajo el indice y con que score
        # para juzgar el retrieval (y el umbral) sin reproducir la consulta a mano.
        rag_fragments=[
            {
                "topic": f.topic,
                "score": f.score,
                "source_url": f.source_url,
                "relevant": f.score >= retrieved.threshold,
            }
            for f in retrieved.all_fragments
        ],
        rag_min_score=retrieved.threshold,
        handoff_triggered=not result.has_evidence and not anonymous,
    )
    if result.has_evidence:
        service.post_bot_message(conversation.conversation_id, result.text)
    elif anonymous:
        service.post_bot_message(
            conversation.conversation_id, prompts.FAQ_NO_EVIDENCE_ANONYMOUS_RESPONSE
        )
    else:
        _handoff(conversation, message, reason="faq_no_evidence", intent=Intent.FAQ,
                 response=prompts.FAQ_NO_EVIDENCE_HANDOFF_RESPONSE, record=False)


def _handoff(
    conversation: Conversation,
    message: Message,
    *,
    reason: str,
    intent: Intent,
    response: str,
    record: bool = True,
) -> None:
    """Handoff minimo (RF-022): sin ticket (F5) y sin Slack (D-016) todavia."""
    started = service.start_handoff(conversation, reason=reason)
    logger.info(
        "ai.handoff",
        extra={
            "conversation_id": conversation.conversation_id,
            "message_id": message.message_id,
            "reason": reason,
            "intent": str(intent),
            "started": started,
        },
    )
    if started:
        service.post_bot_message(conversation.conversation_id, response)
    else:
        # Otro job gano la carrera y la conversacion ya espera asesor: aplica RF-027.
        current = repository.get_conversation(conversation.conversation_id)
        if current is not None:
            _while_bot_off(current)
    if record:
        _record_free(conversation, message, source=f"handoff:{reason}", intent=str(intent),
                     handoff=True)


def _reply_fixed(
    conversation: Conversation,
    message: Message,
    text: str,
    source: str,
    *,
    intent: Intent | None = None,
) -> None:
    service.post_bot_message(conversation.conversation_id, text)
    _record_free(conversation, message, source=source,
                 intent=str(intent) if intent else None)


# ──────────────────────────────────── Apoyos del flujo ────────────────────────────────────


def _log_skip(conversation: Conversation, message: Message, reason: str) -> None:
    logger.debug(
        "ai.debounce.skip",
        extra={
            "conversation_id": conversation.conversation_id,
            "message_id": message.message_id,
            "reason": reason,
        },
    )


def _trailing_user_block(window: list[Message]) -> list[Message]:
    """Los mensajes USER consecutivos al final del hilo: la rafaga que se responde junta."""
    block: list[Message] = []
    for item in reversed(window):
        if item.sender_type != SenderType.USER:
            break
        block.append(item)
    return list(reversed(block))


def _is_repeat(text: str, window: list[Message], block_keys: list[str]) -> bool:
    """D-006: el mismo texto ya fue enviado (y atendido) hace poco. Solo mira mensajes USER
    anteriores al bloque actual: los del bloque son la misma rafaga, no una repeticion."""
    cutoff = minutes_ago_iso(get_settings().trivial_repeat_window_minutes)
    for item in window:
        if item.message_key in block_keys or item.sender_type != SenderType.USER:
            continue
        if item.created_at >= cutoff and trivial.same_message(item.content or "", text):
            return True
    return False


def _already_warned_repeat(window: list[Message]) -> bool:
    """El aviso de repeticion sale una vez: a la segunda repeticion, silencio (el mensaje
    queda guardado igual)."""
    last_bot = _last_bot_message(window)
    return last_bot == prompts.TRIVIAL_REPEAT_RESPONSE


def _last_bot_message(window: list[Message]) -> str | None:
    for item in reversed(window):
        if item.sender_type == SenderType.BOT and item.content:
            return item.content
    return None


def _history(window: list[Message], block_keys: list[str]) -> list[dict[str, str]]:
    """La ventana como turnos user/assistant para el redactor, sin el bloque actual (ese viaja
    como el mensaje) y sin notas SYSTEM (son eventos, no conversacion)."""
    history: list[dict[str, str]] = []
    for item in window:
        if item.message_key in block_keys or not item.content:
            continue
        if item.sender_type == SenderType.USER:
            history.append({"role": "user", "content": item.content})
        elif item.sender_type in (SenderType.BOT, SenderType.ADVISOR):
            history.append({"role": "assistant", "content": item.content})
    return history


# ─────────────────────────────── Contabilidad (AIUsage, T-04) ───────────────────────────────


def _cost(tier: llm.ModelTier, model: str | None, tokens: dict[str, int] | None) -> float:
    """Costo con el precio vigente del modelo que REALMENTE respondio (regla de
    llm-cost-optimizer: nunca un numero recordado despues). Importa pasar el modelo: el
    respaldo del tier tiene otra tarifa y cobrarlo con la del principal subestima."""
    return llm.cost_for(model, tokens, tier=tier)


def _record_classification(
    conversation: Conversation, message: Message, classification: ClassificationResult
) -> None:
    called_model = classification.source == "model"
    usage.record_execution(
        conversation_id=conversation.conversation_id,
        message_id=message.message_id,
        execution_type=usage.CLASSIFICATION,
        intent=str(classification.intent),
        source=classification.rule or classification.source,
        provider=_GOOGLE if called_model else usage.NO_PROVIDER,
        model=classification.model,
        usage=classification.usage,
        estimated_cost_usd=_cost(llm.ModelTier.FAST, classification.model, classification.usage),
        latency_ms=classification.latency_ms,
    )


def _record_free(
    conversation: Conversation,
    message: Message,
    *,
    source: str,
    intent: str | None = None,
    handoff: bool = False,
) -> None:
    """Registra una decision que no pago tokens — la metrica que justifica D-006 y las reglas."""
    usage.record_execution(
        conversation_id=conversation.conversation_id,
        message_id=message.message_id,
        execution_type=usage.RESPONSE,
        intent=intent,
        source=source,
        provider=usage.NO_PROVIDER,
        model=None,
        usage=None,
        estimated_cost_usd=0.0,
        latency_ms=0,
        handoff_triggered=handoff,
    )
