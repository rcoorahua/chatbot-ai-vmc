"""FAQ con RAG (RF-017): recuperar, redactar con evidencia y, sin evidencia, preguntar por el
asesor en vez de inventar (RF-018 / AC-002, revisada por D-029)."""

from backend.agent import followups, prompts, rag, related, writer
from backend.conversations.models import Conversation, Message
from backend.core.metadata import SOURCES
from backend.core.observability import content_preview
from backend.workers.ai import window
from backend.workers.ai.accounting import record_answer
from backend.workers.ai.replies import bot_says, is_anonymous, offer_handoff_confirm
from backend.workers.ai.trace import ctx, logger


def answer_faq(
    conversation: Conversation,
    message: Message,
    text: str,
    context: list[Message],
    block_keys: list[str],
    *,
    source_prefix: str = "",
) -> None:
    """`text` es lo que se busca y se redacta: para un mensaje normal es lo que escribio el
    usuario; para un paso de flujo resuelto (D-028) es la consulta canonica, que si recupera
    evidencia donde "En Vivo" a secas no lo haria. `source_prefix` deja el rastro del flujo
    en AIUsage ("flow:PARTICIPATION:LIVE:model") sin perder la capa que decidio.

    Lo que se BUSCA no siempre es lo que se REDACTA: si el mensaje es una continuacion ("ya
    estoy ahi", "y luego?"), la consulta al indice es la que dio evidencia a la ultima
    respuesta del bot (`window.previous_query`, `agent/followups.py`). Sin eso, un mensaje que
    solo tiene sentido pegado al anterior no se parece a nada del corpus y el caso derivaba por
    "falta de evidencia" teniendo el articulo correcto entre los descartados. El redactor
    sigue recibiendo el texto original mas el historial, que es lo que necesita para
    contestar con naturalidad.
    """
    consulta = followups.build_query(
        text,
        previous_question=window.previous_query(context, block_keys),
        last_bot_message=window.last_bot_open_question(context),
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
        extra=ctx(
            conversation,
            message,
            results=len(fragments),
            siblings=len(retrieved.siblings),
            discarded=len(retrieved.discarded),
            threshold=retrieved.threshold,
            # Si la regla de continuidad intervino, se ve aqui sin reproducir la charla.
            contextualized=consulta.contextualized,
            followup_rule=consulta.rule,
            best_score=round(max((f.score for f in retrieved.all_fragments), default=0.0), 3),
            topics=[f.topic for f in fragments][:5],
            query=content_preview(consulta.text),
        ),
    )
    result = writer.write_answer(
        text,
        [fragment.as_context() for fragment in fragments],
        history=window.history(context, block_keys),
        # D-030: la sesion ya sabe si tiene cuenta; el redactor no lo pregunta.
        user_state=(
            prompts.WRITER_USER_ANONYMOUS
            if is_anonymous(conversation)
            else prompts.WRITER_USER_AUTHENTICATED
        ),
    )
    if result.guardrail:
        # El modelo respondio pero se salio de la evidencia (cifra o enlace ajenos, fuga del
        # prompt): se registra aparte de "sin evidencia" porque el arreglo es distinto (prompt
        # o corpus, no umbral del RAG).
        source = f"guardrail:{result.guardrail}"
    elif result.error:
        # Habia evidencia y el proveedor no respondio (cuota, timeout, 5xx): tampoco es "sin
        # evidencia". Queda con status ERROR y la causa, que es lo que la consola muestra.
        source = "model_unavailable"
    else:
        source = "model" if result.model else "fallback"
    record_answer(
        conversation, message, result=result, retrieved=retrieved, source=source_prefix + source
    )
    if result.has_evidence:
        # La consulta que dio la evidencia viaja con la respuesta: si el usuario contesta "si"
        # o "y luego?", la continuacion busca con ESTA consulta (`window.previous_query`).
        # D-030: ademas la fuente (chip) y las otras preguntas del articulo (botones), las
        # dos sacadas de la evidencia sin llamar a nada. Ojo: con `interaction` en la
        # metadata, `last_bot_open_question` deja de ver esta respuesta como pregunta
        # abierta — correcto, porque ya no termina preguntando si continuar.
        metadata: dict = {
            followups.RAG_QUERY_KEY: consulta.text,
            SOURCES: related.sources(fragments),
        }
        metadata.update(
            related.related_metadata(
                # La pregunta respondida se detecta contra lo que se BUSCO (la consulta), no
                # contra el texto crudo: en un paso de flujo o una continuacion el texto no
                # describe el tema y la consulta si. `candidates` y no `all_fragments`: los
                # hits mas alla de top_k tambien cuentan (persona juridica era el quinto).
                # Solo preguntas: el asesor ya no se ofrece bajo una respuesta que SI
                # resolvio (2026-09-08, Aaron: el bot esta para quitar carga a los asesores).
                related.related_questions(consulta.text, fragments, retrieved.candidates),
            )
        )
        bot_says(conversation, result.text, metadata=metadata)
    elif result.error:
        # El dato existe, el redactor no contesto: se dice la verdad (no "no tengo ese dato"),
        # se invita a reintentar y se ofrece el asesor con los mismos botones de si/no.
        offer_handoff_confirm(
            conversation, message, text=prompts.MODEL_UNAVAILABLE_CONFIRM_RESPONSE
        )
    else:
        offer_handoff_confirm(conversation, message)
