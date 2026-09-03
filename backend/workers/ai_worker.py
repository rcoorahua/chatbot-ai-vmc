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
from datetime import timedelta

from backend.agent import (
    flows,
    followups,
    guardrails,
    prompts,
    quota,
    rag,
    trivial,
    usage,
    writer,
)
from backend.agent.classifier import ClassificationResult, classify
from backend.agent.heuristics import classify_by_rules
from backend.agent.intents import Intent
from backend.conversations import forms, repository, service
from backend.conversations.models import (
    Conversation,
    ConversationStatus,
    Message,
    MessageStatus,
    SenderType,
    UserType,
)
from backend.core import llm
from backend.core.clock import minutes_ago_iso, to_iso, utc_now, utc_now_iso
from backend.core.config import get_settings
from backend.core.jobs import AIJob
from backend.core.observability import configure_logging, content_preview

configure_logging()
logger = logging.getLogger(__name__)

_GOOGLE = "GOOGLE"

# Reglas de `followups.is_continuation` que no dejan duda: un acuse ("si", "listo") o un pedido
# explicito de seguir ("y luego?"). Con ellas el clasificador sobra. "responde_al_bot" (texto
# corto cualquiera tras una pregunta del bot) es mas debil y sigue clasificandose con modelo.
_CERTAIN_CONTINUATIONS = frozenset({"acuse", "pide_seguir"})

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
            _attend(conversation, message, ip_hash=job.ip_hash)
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


def _attend(conversation: Conversation, message: Message, ip_hash: str | None = None) -> None:
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

    # ── Continuidad (TD-009): ¿el mensaje solo tiene sentido pegado a lo que pregunto el bot? ──
    # Se decide ANTES de los triviales y de la repeticion porque cambia lo que significan: tras
    # "¿te explico el siguiente paso?", un "ok" no es un "gracias" de cierre, y el tercer "si"
    # seguido no es un mensaje repetido: es el paso 3 de una explicacion que el propio bot
    # pidio continuar (conversaciones reales del 2026-09-03). Reglas sobre texto, sin modelo.
    bot_asked = followups.bot_asked_something(_last_bot_open_question(window))
    continuation, followup_rule = followups.is_continuation(text, bot_asked=bot_asked)

    # ── D-006: triviales, sin llamada IA ──
    kind = trivial.match_trivial(text)
    if kind == "thanks" and bot_asked and followup_rule == "acuse":
        # "ok", "listo", "vale" contestan la pregunta abierta del bot: la explicacion sigue.
        # "gracias" o "chau" no son acuses y cierran como siempre.
        kind = None
    if kind == "greeting":
        _reply_fixed(conversation, message, prompts.TRIVIAL_GREETING_RESPONSE, "trivial_greeting")
        return
    if kind == "thanks":
        _reply_fixed(conversation, message, prompts.TRIVIAL_THANKS_RESPONSE, "trivial_thanks")
        return
    if kind == "identity":
        _reply_fixed(conversation, message, prompts.TRIVIAL_IDENTITY_RESPONSE, "trivial_identity")
        return
    # Una continuacion nunca es "repetido": responde a la ULTIMA pregunta del bot aunque use la
    # misma palabra que la vez anterior. El volumen lo frena el rate limit (D-005).
    if not continuation and _is_repeat(text, window, block_keys):
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
        # Un intento de manipulacion no deja un flujo colgado esperando datos (MAPEO.md §4.2).
        _clear_flow_if_active(conversation)
        _reply_fixed(
            conversation, message, _GUARDRAIL_RESPONSES[verdict.kind],
            f"guardrail:{verdict.kind}:{verdict.rule}",
        )
        return

    # ── D-028: flujos guiados con quick replies (MAPEO.md) — reglas y estado, sin IA ──
    # Antes del clasificador a proposito: un click de boton ya trae la intencion estructurada
    # y una respuesta corta ("En Vivo") solo tiene sentido con el estado del flujo.
    anonymous = conversation.user_type == UserType.ANONYMOUS
    if _handle_flow(conversation, message, text, window, block_keys, anonymous=anonymous,
                    ip_hash=ip_hash):
        return

    # ── T-09 / D-027: tope de ejecuciones de IA por actor ──
    # Se decide ANTES de tocar un modelo. Las reglas deterministas siguen vivas con la cuota
    # agotada (no cuestan): "quiero un asesor" — justo lo que promete el mensaje fijo —
    # deriva igual. Solo lo que NECESITA un modelo (clasificar lo ambiguo, redactar una FAQ)
    # recibe la respuesta fija de cuota. En dev todo esta en 0 y este bloque no toca la tabla.
    rules_verdict = classify_by_rules(text)
    needs_model = rules_verdict.intent is None or rules_verdict.intent == Intent.FAQ
    if needs_model and not _spend_quota_or_reply(conversation, message, ip_hash):
        return  # cuota agotada: ya salio la respuesta fija, gratis

    # ── RF-015/016: clasificar (reglas → tier FAST; Gemini orquesta por TD-008) ──
    if rules_verdict.intent is None and followup_rule in _CERTAIN_CONTINUATIONS:
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
        classification = classify(text, _last_bot_message(window))
    _record_classification(conversation, message, classification)
    if classification.intent == Intent.OTHER:
        _reply_fixed(conversation, message, prompts.OTHER_INTENT_RESPONSE, "fixed_other",
                     intent=classification.intent)
    elif classification.intent == Intent.CATALOG:
        # Fijo mientras D-011 (contrato HERALD) siga abierta; T-23 lo reemplaza.
        _reply_fixed(conversation, message, prompts.CATALOG_FALLBACK_RESPONSE, "fixed_catalog",
                     intent=classification.intent)
    elif classification.intent == Intent.ADVISOR:
        # D-029: anonimo y autenticado derivan por formulario (RF-003 pide el correo al
        # anonimo); el bot ofrece la tarjeta y sigue atendiendo hasta que la envien.
        _offer_handoff_form(conversation, message,
                            reason=classification.rule or "advisor_intent",
                            intent=classification.intent, response=prompts.HANDOFF_OFFER_RESPONSE)
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
    source_prefix: str = "",
) -> None:
    """FAQ con RAG (RF-017): recuperar, redactar con evidencia, y sin evidencia derivar en vez
    de inventar (RF-018 / AC-002).

    `text` es lo que se busca y se redacta: para un mensaje normal es lo que escribio el
    usuario; para un paso de flujo resuelto (D-028) es la consulta canonica, que si recupera
    evidencia donde "En Vivo" a secas no lo haria. `source_prefix` deja el rastro del flujo
    en AIUsage ("flow:PARTICIPATION:LIVE:model") sin perder la capa que decidio.

    Lo que se BUSCA no siempre es lo que se REDACTA: si el mensaje es una continuacion ("ya
    estoy ahi", "y luego?"), la consulta al indice es la que dio evidencia a la ultima
    respuesta del bot (`_previous_query`, `agent/followups.py`). Sin eso, un mensaje que solo
    tiene sentido pegado al anterior no se parece a nada del corpus y el caso derivaba por
    "falta de evidencia" teniendo el articulo correcto entre los descartados. El redactor
    sigue recibiendo el texto original mas el historial, que es lo que necesita para
    contestar con naturalidad.
    """
    consulta = followups.build_query(
        text,
        previous_question=_previous_query(window, block_keys),
        last_bot_message=_last_bot_open_question(window),
    )
    if consulta.rule == "responde_al_bot":
        # La regla debil: un texto corto tras una pregunta del bot puede ser la respuesta
        # ("en la web") o un tema nuevo dicho a medias ("y los subascoins"). Lo decide el
        # indice, no una adivinanza: si el texto se sostiene solo, gana el texto; si no, la
        # pregunta previa. Cuesta una consulta mas a Pinecone, ninguna a un modelo.
        literal = rag.retrieve(text)
        if literal.relevant:
            consulta = followups.Query(text=text, contextualized=False, rule="literal")
            retrieved = literal
        else:
            retrieved = rag.retrieve(consulta.text)
    else:
        retrieved = rag.retrieve(consulta.text)
    fragments = retrieved.relevant
    logger.debug(
        "ai.rag",
        extra={
            "conversation_id": conversation.conversation_id,
            "message_id": message.message_id,
            "results": len(fragments),
            "discarded": len(retrieved.discarded),
            "threshold": retrieved.threshold,
            # Si la regla de continuidad intervino, se ve aqui sin reproducir la charla.
            "contextualized": consulta.contextualized,
            "followup_rule": consulta.rule,
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
    source = source_prefix + source
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
        handoff_triggered=not result.has_evidence,
    )
    if result.has_evidence:
        # La consulta que dio la evidencia viaja con la respuesta: si el usuario contesta "si"
        # o "y luego?", la continuacion busca con ESTA consulta (`_previous_query`).
        _bot_says(conversation, result.text, metadata={followups.RAG_QUERY_KEY: consulta.text})
    else:
        _offer_handoff_confirm(conversation, message)


def _offer_handoff_form(
    conversation: Conversation,
    message: Message,
    *,
    reason: str,
    intent: Intent,
    response: str,
    record: bool = True,
) -> None:
    """D-029: pedir asesor ya no deriva de inmediato. El bot ofrece la TARJETA de formulario
    (asunto y detalle; nombre, correo y telefono si es anonimo — RF-003) y la derivacion la
    hace `POST /chat/.../handoff` cuando el usuario la envia. Hasta entonces el bot sigue
    encendido: quien ignora la tarjeta puede seguir preguntando. Sin ticket (F5) ni Slack
    (D-016) todavia."""
    # Con un humano en camino, ningun flujo guiado sigue esperando datos (MAPEO.md §4.2).
    _clear_flow_if_active(conversation)
    anonymous = conversation.user_type == UserType.ANONYMOUS
    spec = forms.handoff_form_spec(
        anonymous=anonymous, needs_email=not anonymous and not conversation.user_email
    )
    _bot_says(conversation, response, metadata=spec)
    logger.info(
        "ai.handoff.offer",
        extra={
            "conversation_id": conversation.conversation_id,
            "message_id": message.message_id,
            "reason": reason,
            "intent": str(intent),
            "anonymous": anonymous,
        },
    )
    if record:
        _record_free(conversation, message, source=f"handoff_offer:{reason}",
                     intent=str(intent), handoff=True)


def _offer_handoff_confirm(conversation: Conversation, message: Message) -> None:
    """Sin evidencia (RF-018): se reconoce el limite y se PREGUNTA si quiere un asesor.

    Revision de D-029 (2026-09-02, Aaron): antes esto publicaba el formulario de una, y el
    usuario terminaba con una tarjeta de datos delante sin haber pedido nada. Ahora sale la
    pregunta con botones si/no y el formulario espera a que conteste que si.

    Ojo con lo que NO cambia: cuando el usuario PIDE un asesor (intent ADVISOR), el formulario
    sigue saliendo directo — volver a preguntarle "¿quieres un asesor?" a quien acaba de
    pedirlo es un turno de mas por nada.
    """
    # Se RELEE la conversacion: si en este mismo job se limpio un flujo guiado (un paso que se
    # resolvio y no trajo evidencia), `conversation.flow_version` quedo viejo y la transicion
    # fallaria por condicion — dejando al usuario sin pregunta y sin respuesta. Lo encontro
    # tests/test_ai_worker_flows.py::...sin_evidencia_al_resolver...
    current = repository.get_conversation(conversation.conversation_id) or conversation
    definition = flows.FLOWS[flows.HANDOFF_CONFIRM]
    _offer_flow_step(
        current, message, definition, definition.steps[0],
        text=prompts.FAQ_NO_EVIDENCE_CONFIRM_RESPONSE,
    )


def _reply_fixed(
    conversation: Conversation,
    message: Message,
    text: str,
    source: str,
    *,
    intent: Intent | None = None,
) -> None:
    _bot_says(conversation, text)
    _record_free(conversation, message, source=source,
                 intent=str(intent) if intent else None)


def _bot_says(conversation: Conversation, text: str, *, metadata: dict | None = None) -> None:
    """Toda respuesta del bot sale por aqui: arrastra el TTL de la conversacion anonima
    (D-029) para que sus mensajes caduquen con ella."""
    service.post_bot_message(
        conversation.conversation_id, text, metadata=metadata, expires_at=conversation.expires_at
    )


# ───────────────────────── Flujos guiados (D-028, mapeo en MAPEO.md) ─────────────────────────


def _current_flow(
    conversation: Conversation,
) -> tuple[flows.FlowDefinition, flows.FlowStep, bool] | None:
    """(definicion, paso, vigente) del flujo activo; None si no hay flujo o ya no existe la
    definicion (un deploy pudo retirarla: el estado viejo no debe romper nada)."""
    if not conversation.active_flow:
        return None
    definition = flows.FLOWS.get(conversation.active_flow)
    step = definition.step(conversation.flow_step or "") if definition else None
    if definition is None or step is None:
        return None
    expired = bool(conversation.flow_expires_at) and conversation.flow_expires_at <= utc_now_iso()
    return definition, step, not expired


def _clear_flow_if_active(conversation: Conversation) -> None:
    """Limpieza best-effort: si otro proceso movio el flujo primero, no hay nada que hacer."""
    if conversation.active_flow:
        repository.clear_flow_state(
            conversation.conversation_id, expected_version=conversation.flow_version
        )


def _handle_flow(
    conversation: Conversation,
    message: Message,
    text: str,
    window: list[Message],
    block_keys: list[str],
    *,
    anonymous: bool,
    ip_hash: str | None = None,
) -> bool:
    """True si el flujo guiado atendio el mensaje (D-028). El orden importa:

    1. flujo activo + click valido o texto que resuelve el slot → responder con la consulta
       canonica y cerrar el flujo;
    2. flujo activo + texto que NO resuelve → interrupcion FAQ: el flujo queda esperando y el
       mensaje sigue el pipeline normal (False);
    3. sin flujo + disparador con el dato ya en el texto ("participar en una En Vivo") →
       respuesta directa, sin botones ni estado;
    4. sin flujo + disparador sin dato → persistir el paso y ofrecer los botones (sin IA).
    """
    active = _current_flow(conversation)
    if active is not None:
        definition, step, vigente = active
        if not vigente:
            # Vencio (24 h): se limpia y este mensaje se atiende como cualquier otro.
            _clear_flow_if_active(conversation)
        else:
            interaction = (message.metadata or {}).get("interaction")
            value = flows.validate_interaction(
                step, interaction, current_version=conversation.flow_version
            ) if interaction is not None else None
            if value is None:
                value = flows.extract_slot_value(step, text)
            if definition.name == flows.HANDOFF_CONFIRM:
                # Una pregunta de si/no vale para el turno siguiente y nada mas: si el usuario
                # la ignora y pregunta otra cosa, se limpia. Dejarla viva 24 h como a un flujo
                # del corpus haria que un "si" de mañana derivara por un tema ya olvidado.
                _clear_flow_if_active(conversation)
                if value is None:
                    return False  # sigue el pipeline normal con su pregunta nueva
                _resolve_handoff_confirm(conversation, message, value)
                return True
            if value is None:
                return False  # interrupcion: el flujo espera hasta resolverse o vencer
            # T-09/D-027: resolver el paso llama al redactor (pagado). Con la cuota agotada
            # el flujo QUEDA esperando: al renovarse, "en vivo" escrito lo resuelve igual.
            if not _spend_quota_or_reply(conversation, message, ip_hash):
                return True
            _clear_flow_if_active(conversation)
            _answer_flow_step(
                conversation, message, definition, step, value, window, block_keys,
                anonymous=anonymous,
            )
            return True

    flow_name = flows.detect_flow_start(text)
    if flow_name is None:
        return False
    definition = flows.FLOWS[flow_name]
    step = definition.steps[0]
    direct = flows.extract_slot_value(step, text)
    if direct is not None:
        if not _spend_quota_or_reply(conversation, message, ip_hash):
            return True
        _answer_flow_step(
            conversation, message, definition, step, direct, window, block_keys,
            anonymous=anonymous,
        )
        return True
    # Ofrecer los botones no llama a ningun modelo: no gasta cuota ni se bloquea por ella.
    _offer_flow_step(conversation, message, definition, step)
    return True


def _offer_flow_step(
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
    version = repository.set_flow_state(
        conversation.conversation_id,
        flow=definition.name,
        step=step.action_id,
        slots={},
        expires_at=expires_at,
        expected_version=conversation.flow_version,
    )
    if version is None:
        # Otro job gano la transicion (rafaga D-020): ese publico los botones, aqui silencio.
        _log_skip(conversation, message, "flow_race")
        return
    _bot_says(
        conversation,
        text or step.prompt,
        metadata=flows.quick_replies_metadata(definition, step, version),
    )
    _record_free(conversation, message, source=f"flow:{definition.name}:offered")


def _resolve_handoff_confirm(
    conversation: Conversation, message: Message, value: str
) -> None:
    """El usuario contesto la pregunta de "¿te conecto con un asesor?". Gratis en los dos
    caminos: publicar el formulario o despedirse no cuesta ninguna llamada a modelo."""
    logger.info(
        "ai.handoff.confirm",
        extra={
            "conversation_id": conversation.conversation_id,
            "message_id": message.message_id,
            "value": value,
        },
    )
    if value == "YES":
        _offer_handoff_form(
            conversation, message, reason="faq_no_evidence", intent=Intent.ADVISOR,
            response=prompts.HANDOFF_OFFER_RESPONSE,
        )
        return
    _reply_fixed(
        conversation, message, prompts.HANDOFF_DECLINED_RESPONSE, "handoff_declined",
        intent=Intent.ADVISOR,
    )


def _answer_flow_step(
    conversation: Conversation,
    message: Message,
    definition: flows.FlowDefinition,
    step: flows.FlowStep,
    value: str,
    window: list[Message],
    block_keys: list[str],
    *,
    anonymous: bool,
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
        extra={
            "conversation_id": conversation.conversation_id,
            "message_id": message.message_id,
            "flow": definition.name,
            "step": step.action_id,
            "value": value,
        },
    )
    _answer_faq(
        conversation, message, query, window, block_keys, anonymous,
        source_prefix=f"flow:{definition.name}:{value}:",
    )


# ───────────────────────── Cuota de IA (T-09 / D-027, rev. 2026-09-01) ─────────────────────────


def _quota_kwargs(conversation: Conversation, ip_hash: str | None) -> dict:
    return {
        "anonymous": conversation.user_type == UserType.ANONYMOUS,
        "user_id": conversation.user_id,
        "conversation_id": conversation.conversation_id,
        "ip_hash": ip_hash,
    }


def _spend_quota_or_reply(
    conversation: Conversation, message: Message, ip_hash: str | None
) -> bool:
    """True = hay cuota (y queda gastada 1 ejecucion); False = agotada y ya se respondio el
    mensaje fijo. Con los topes en 0 (dev) siempre True sin tocar la tabla."""
    anonymous = conversation.user_type == UserType.ANONYMOUS
    if not quota.enabled(anonymous=anonymous):
        return True
    qk = _quota_kwargs(conversation, ip_hash)
    if quota.exhausted(**qk):
        _reply_quota(conversation, message)
        return False
    quota.spend(**qk)
    return True


def _reply_quota(conversation: Conversation, message: Message) -> None:
    """Respuesta fija de cuota agotada (gratis): al anonimo lo orienta a crear cuenta (que
    ademas duplica su cuota y habilita el asesor, D-002); al autenticado, a pedir un asesor —
    ruta que sale por reglas y funciona sin modelo."""
    anonymous = conversation.user_type == UserType.ANONYMOUS
    _reply_fixed(
        conversation,
        message,
        prompts.QUOTA_EXHAUSTED_ANON_RESPONSE if anonymous
        else prompts.QUOTA_EXHAUSTED_AUTH_RESPONSE,
        "quota:exhausted",
    )


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


def _last_bot_open_question(window: list[Message]) -> str | None:
    """El último mensaje del bot, SOLO si era una pregunta abierta.

    Un mensaje con `interaction` (los botones de un flujo, el sí/no del asesor, el formulario)
    tambien termina en "?", pero es una pregunta ESTRUCTURADA: sus respuestas validas las
    resuelve la maquinaria de flujos, y cualquier otra cosa que escriba el usuario es un tema
    nuevo, no la continuacion del anterior. Devolverla aqui hacia que "mejor dime cuanto es la
    comision", escrito despues de "¿quieres un asesor?", heredara el tema viejo y se buscara
    la pregunta equivocada.
    """
    for item in reversed(window):
        if item.sender_type != SenderType.BOT or not item.content:
            continue
        if (item.metadata or {}).get("interaction"):
            return None
        return item.content
    return None


def _previous_user_texts(window: list[Message], block_keys: list[str]) -> list[str]:
    """Lo que el usuario escribio ANTES de la rafaga actual, en orden cronologico. Es de donde
    `followups` saca la pregunta que da tema a una continuacion."""
    return [
        item.content
        for item in window
        if item.sender_type == SenderType.USER
        and item.message_key not in block_keys
        and item.content
    ]


def _previous_query(window: list[Message], block_keys: list[str]) -> str | None:
    """La consulta que sostiene una continuacion: la que dio evidencia a la ultima respuesta
    del bot (viaja en su metadata, `followups.RAG_QUERY_KEY`) y, si esa respuesta no la trae
    (fija, con botones, o anterior a este campo), la ultima pregunta del usuario del historial.

    Preferir la de la respuesta cubre dos casos que el historial no cubre: un paso de flujo
    (D-028), cuya evidencia salio de la consulta canonica y no del texto del boton ("Oferta
    En Vivo" recupera peor), y una explicacion de varios "si" seguidos, donde la pregunta
    original ya quedo fuera de la mirada hacia atras de `last_user_question`.
    """
    for item in reversed(window):
        if item.message_key in block_keys or item.sender_type != SenderType.BOT:
            continue
        query = (item.metadata or {}).get(followups.RAG_QUERY_KEY)
        if query:
            return str(query)
        break  # la ultima respuesta del bot no salio del indice: decide el historial
    return followups.last_user_question(_previous_user_texts(window, block_keys))


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
