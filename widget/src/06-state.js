
  // ───────────────────────────────── Mensajes ─────────────────────────────────

  function upsertMessages(incoming) {
    let added = 0;
    const known = new Set(state.messages.map((m) => m.message_id));
    for (const message of incoming) {
      if (known.has(message.message_id)) continue;
      state.messages.push(message);
      known.add(message.message_id);
      added += 1;
      // Llego respuesta (bot, asesor o nota de sistema): se acabo la espera.
      if (message.sender_type !== SENDER.USER) state.typingSince = null;
      if (message.client_message_id) state.pending.delete(message.client_message_id);
      if (!state.lastKey || message.message_key > state.lastKey) state.lastKey = message.message_key;
      if (!state.firstKey || message.message_key < state.firstKey) state.firstKey = message.message_key;
    }
    if (added) state.messages.sort((a, b) => (a.message_key < b.message_key ? -1 : 1));
    return added;
  }

  // ───────────────────────── Conversaciones: hilo del bot + casos (D-029) ─────────────────────────

  function lastMessage() {
    return state.messages[state.messages.length - 1] || null;
  }

  function isAnonymous() {
    return !state.session || state.session.userType !== USER_TYPE.AUTHENTICATED;
  }

  function threadId() {
    return state.session ? state.session.conversationId : null;
  }

  function isThread(conv) {
    return !conv || conv.kind !== KIND.CASE;
  }

  function waitingAdvisor(conv) {
    return Boolean(conv) && (conv.status === STATUS.PENDING_ADVISOR || conv.status === STATUS.IN_ATTENTION);
  }

  function hasOpenCase() {
    return state.conversations.some((c) => c.kind === KIND.CASE && c.status !== STATUS.CLOSED);
  }

  /** Estado fresco de una conversacion (viene en cada sondeo): se refleja en la lista. */
  function applyConversation(conv) {
    if (!conv) return;
    if (conv.conversation_id === state.activeId) state.conversation = conv;
    const i = state.conversations.findIndex((c) => c.conversation_id === conv.conversation_id);
    if (i >= 0) state.conversations[i] = conv;
    else if (conv.kind === KIND.CASE) state.conversations.push(conv);
    else state.conversations.unshift(conv);
  }

  async function fetchConversations() {
    const data = await withSession((session) =>
      request("GET", "/chat/conversations", undefined, session.token)
    );
    const primera = !state.lastListAt;
    state.lastListAt = Date.now();
    for (const conv of data.conversations) {
      const seen = state.seenAt[conv.conversation_id];
      // Con el panel cerrado, un caso que avanzo desde la ultima lista es una novedad para
      // el contador del boton. La primera carga solo toma la foto.
      if (!primera && !state.open && seen && conv.last_message_at > seen) state.unread += 1;
      state.seenAt[conv.conversation_id] = conv.last_message_at;
    }
    state.conversations = data.conversations;
    const active = data.conversations.find((c) => c.conversation_id === state.activeId);
    if (active) state.conversation = active;
    return data.conversations;
  }

  function refreshList() {
    if (isAnonymous()) return;
    fetchConversations().then(render, render);
  }

  /** Guarda los mensajes de la conversacion activa y carga (o estrena) otra. */
  function switchConversation(id) {
    if (!id || id === state.activeId) {
      if (state.view !== "messages") setView("messages");
      return;
    }
    if (state.activeId) {
      state.threads.set(state.activeId, {
        messages: state.messages,
        lastKey: state.lastKey,
        firstKey: state.firstKey,
        hasMore: state.hasMore,
        conversation: state.conversation,
      });
    }
    const saved = state.threads.get(id);
    state.activeId = id;
    state.messages = saved ? saved.messages : [];
    state.lastKey = saved ? saved.lastKey : null;
    state.firstKey = saved ? saved.firstKey : null;
    state.hasMore = saved ? saved.hasMore : false;
    state.conversation = saved
      ? saved.conversation
      : state.conversations.find((c) => c.conversation_id === id) || null;
    state.typingSince = null;
    scrollToBottomNext();
    state.formError = null;
    state.view = "messages";
    state.unread = 0;
    render();
    if (state.loading) state.pollAgain = true; // el sondeo en vuelo era de la otra
    else poll();
  }

  function openThread() {
    switchConversation(threadId());
  }

  function openMessagesTab() {
    if (isAnonymous()) openThread();
    else setView("inbox");
  }

  // ───────────────────────────────── Sondeo (TD-001) ─────────────────────────────────

  async function poll() {
    if (state.loading) return;
    // El anonimo no tiene sesion hasta que abre el chat: sin sesion no hay fila que sondear
    // (y crearla desde aqui haria una conversacion por cada visitante de VMC).
    if (!state.session && !wantsAuthenticated()) return;
    const gen = generation;
    state.loading = true;
    try {
      await ensureSession();
      const listDue = !isAnonymous() && Date.now() - state.lastListAt > CONFIG.listEveryMs;
      if (listDue) await fetchConversations();
      // Cerrado y autenticado: la lista ya cubrio todos los casos en UNA llamada — salvo que
      // se espere al bot en el hilo, que solo se ve sondeando ese hilo.
      if (state.open || isAnonymous() || waitingForBot()) await pollActive();
      state.failures = 0;
      if (!state.open) updateLauncher();
    } catch (error) {
      if (isStale(error)) return; // hubo un reset en medio: ese ya programo lo suyo
      state.failures += 1;
      render(); // muestra el aviso de sin conexion si aplica
    } finally {
      if (gen === generation) {
        state.loading = false;
        if (state.pollAgain) {
          state.pollAgain = false;
          poll();
        } else {
          schedulePoll();
        }
      }
    }
  }

  async function pollActive() {
    const id = state.activeId;
    if (!id) return;
    const query =
      `?limit=${CONFIG.pageSize}` +
      (state.lastKey ? `&after=${encodeURIComponent(state.lastKey)}` : "");
    const data = await withSession((session) =>
      request("GET", `/chat/conversations/${id}/messages${query}`, undefined, session.token)
    );
    if (id !== state.activeId) return; // el usuario cambio de conversacion mientras tanto
    const initial = !state.lastKey;
    const before = state.messages.length;
    const added = upsertMessages(data.messages);
    if (initial) {
      state.hasMore = Boolean(data.has_more);
      if (data.next_before) state.firstKey = data.next_before;
    }
    const statusChanged =
      !state.conversation || state.conversation.status !== data.conversation.status;
    applyConversation(data.conversation);
    if (state.conversation && !state.conversation.bot_enabled) state.typingSince = null;
    const ajenos = data.messages.filter((m) => m.sender_type !== SENDER.USER).length;
    if (added && before > 0 && !(state.open && state.view === "messages")) {
      state.unread += ajenos;
    }
    // Con el hilo abierto pero el usuario leyendo mas arriba: no se le mueve la vista, se le
    // avisa con la pildora de "hay mensajes abajo".
    if (added && ajenos && state.open && state.view === "messages" && !state.stickToBottom) {
      state.unseenBelow += ajenos;
    }
    if (added || statusChanged || state.offline) render();
  }

  async function loadOlder() {
    if (!state.hasMore || !state.firstKey || state.loadingOlder) return;
    state.loadingOlder = true;
    const id = state.activeId;
    try {
      const data = await withSession((session) =>
        request(
          "GET",
          `/chat/conversations/${id}/messages?limit=${CONFIG.pageSize}` +
            `&before=${encodeURIComponent(state.firstKey)}`,
          undefined,
          session.token
        )
      );
      if (id !== state.activeId) return;
      state.stickToBottom = false;
      upsertMessages(data.messages);
      state.hasMore = Boolean(data.has_more);
      if (data.next_before) state.firstKey = data.next_before;
    } catch (error) {
      if (isStale(error)) return;
      /* el boton sigue ahi para reintentar */
    } finally {
      if (id === state.activeId) {
        state.loadingOlder = false;
        render();
      }
    }
  }
