
  function jitter(ms) {
    return Math.round(ms * (0.85 + Math.random() * 0.3));
  }

  /** Se espera una respuesta del bot: el ultimo mensaje propio se confirmo hace poco y el bot
   *  esta encendido. Vence sola a los `typingMaxMs` — tambien con el panel cerrado, donde no
   *  hay render que la retire — para que un bot que nunca contesta no deje el sondeo rapido
   *  encendido para siempre. */
  function waitingForBot() {
    if (!state.typingSince) return false;
    if (Date.now() - state.typingSince > CONFIG.typingMaxMs) {
      state.typingSince = null;
      return false;
    }
    return !state.conversation || state.conversation.bot_enabled;
  }

  /** Cuanto esperar hasta el proximo sondeo; 0 = nada puede llegar, no se sondea. */
  function pollDelay() {
    if (state.failures) {
      const factor = Math.pow(2, state.failures - 1);
      return jitter(Math.min(CONFIG.backoffMaxMs, CONFIG.backoffBaseMs * factor));
    }
    const conv = state.conversation;
    // Solo un caso (autenticado) puede estar CLOSED: ahi lo unico que cambia es la lista.
    if (conv && conv.status === STATUS.CLOSED) return state.open ? jitter(CONFIG.listEveryMs) : 0;
    // Esperando al bot se sondea rapido este el panel abierto o cerrado: cerrado, la
    // respuesta tiene que llegar al contador del boton. Antes el sondeo se detenia al
    // cerrar y el badge no se enteraba hasta reabrir (DETAILS.md §4.19).
    if (waitingForBot()) return jitter(CONFIG.pollWaitingMs);
    if (state.open) return jitter(waitingAdvisor(conv) ? CONFIG.pollAdvisorMs : CONFIG.pollOpenMs);
    // Cerrado: solo los casos del autenticado pueden traer novedades (una llamada a la lista).
    return !isAnonymous() && hasOpenCase() ? jitter(CONFIG.pollClosedMs) : 0;
  }

  function schedulePoll() {
    clearTimeout(state.pollTimer);
    if (document.visibilityState === "hidden") return; // se reanuda en visibilitychange
    if (!state.session) return;
    const delay = pollDelay();
    if (!delay) return;
    state.pollTimer = setTimeout(poll, delay);
  }

  // ───────────────────────── Formulario de asesor (D-029, solo autenticado) ─────────────────────────

  /** Contactar: todos los campos son obligatorios. Si falta alguno, TODOS los que falten
   *  ganan asterisco y aviso a la vez (marcar uno por click es hacer dar tres clicks por
   *  tres campos); si no, se envia y se entra al caso nuevo. */
  async function submitHandoff(spec) {
    if (state.formBusy) return;
    const values = {};
    for (const field of spec.fields) {
      const value = String(state.formDraft[field.name] || "").trim();
      if (value) values[field.name] = value;
    }
    const faltan = spec.fields.filter((field) => !values[field.name]).map((field) => field.name);
    if (faltan.length) {
      state.formMissing = new Set(faltan);
      state.formError = null;
      render();
      return;
    }
    state.formBusy = true;
    state.formError = null;
    render();
    const id = state.activeId;
    try {
      const data = await withSession((session) =>
        request("POST", `/chat/conversations/${id}/handoff`, values, session.token)
      );
      state.formBusy = false;
      state.formDraft = {};
      state.dismissedForm = null;
      markFormGone();
      // Se abrio un caso aparte: se entra a el y el hilo sigue con el bot.
      applyConversation(data.conversation);
      await fetchConversations().catch(() => null);
      switchConversation(data.conversation.conversation_id);
    } catch (error) {
      if (isStale(error)) return; // cambio de usuario en medio del envio: ya no hay formulario
      state.formBusy = false;
      const detail = error.detail;
      state.formError = {
        field: detail && typeof detail === "object" ? detail.field : null,
        message:
          (detail && typeof detail === "object" && detail.detail) ||
          (typeof detail === "string" ? detail : null) ||
          TEXT.formFailed,
      };
      render();
    }
  }

  /** El proximo render aterriza abajo y olvida la pildora de "hay mensajes abajo". */
  function scrollToBottomNext() {
    state.stickToBottom = true;
    state.unseenBelow = 0;
  }

  function sendMessage(text, interaction) {
    scrollToBottomNext(); // lo propio siempre lleva la vista abajo
    const content = text.trim();
    if (!content) return;
    const clientMessageId = newClientMessageId();
    state.pending.set(clientMessageId, {
      content,
      // El evento estructurado del quick reply (D-028): viaja con el mensaje y el servidor
      // lo valida contra el paso vigente — el texto solo es lo que se ve en el hilo.
      interaction: interaction || null,
      status: "sending",
      createdAt: new Date().toISOString(),
      conversationId: state.activeId,
    });
    render();
    deliver(clientMessageId);
  }

  async function deliver(clientMessageId) {
    const draft = state.pending.get(clientMessageId);
    if (!draft) return;
    draft.status = "sending";
    render();
    // El hilo de la sesion de AHORA. Si `withSession` la rehace tras un 404 (dynamodb-local
    // reiniciado, sesion vencida), el visitante recibe un hilo con id NUEVO y el borrador que
    // era del hilo viejo tiene que ir al nuevo. Antes reintentaba contra el id muerto (404
    // otra vez) y, como `dropSession` ya habia vaciado `pending`, el fallo no dejaba burbuja
    // ni "Reintentar": el mensaje se perdia en silencio (auditoria 2026-09-06).
    const threadBefore = state.session ? state.session.conversationId : null;
    let target = draft.conversationId;
    try {
      const data = await withSession((session) => {
        target =
          !draft.conversationId || draft.conversationId === threadBefore
            ? session.conversationId
            : draft.conversationId;
        return request(
          "POST",
          `/chat/conversations/${target}/messages`,
          Object.assign(
            { client_message_id: clientMessageId, content: draft.content },
            draft.interaction ? { interaction: draft.interaction } : null
          ),
          session.token
        );
      });
      state.pending.delete(clientMessageId);
      if (target === state.activeId) upsertMessages([data.message]);
      // El mensaje quedo durable (202): a partir de aqui se espera respuesta — del bot. Con
      // un asesor en el caso la espera es de una persona y no se promete "escribiendo".
      if (!state.conversation || state.conversation.bot_enabled) state.typingSince = Date.now();
      schedulePoll(); // cadencia rapida mientras se espera
    } catch (error) {
      if (isStale(error)) return; // el borrador era de otro usuario: ya se descarto
      if (!state.pending.has(clientMessageId)) {
        // La sesion se rehizo a mitad del envio: el borrador vuelve a la lista, en el hilo
        // nuevo, para que se vea fallido y se pueda reintentar.
        draft.conversationId = target;
        state.pending.set(clientMessageId, draft);
      }
      draft.status = "failed";
      draft.error = error.message;
      draft.rateLimited = error.status === 429;
      if (error.status === 409) poll(); // cerrada mientras escribia: refrescar el estado
    }
    render();
  }

  // ───────────────────────────────── Render ─────────────────────────────────

  let root; // shadow root
  let panelEl;
  let launcherEl;
  let launcherIconEl;
  let launcherBadgeEl;
  let lastViewKey = null; // vista dibujada por ultima vez, para animar solo los cambios reales
  let lastViewDepth = 0; // posicion de esa vista, para saber hacia donde cruzar
  // El render que dibuja el formulario tras la animacion: no debe volver a pedirla (D-030).
  let dibujandoFormulario = false;

  const VIEW_ORDER = { home: 0, inbox: 1, messages: 1.3, help: 2 };
