
  function renderMessages() {
    const name = displayName();
    const items = [];
    let lastDay = null;
    const pushDay = (iso) => {
      const label = dayLabel(iso);
      if (label && label !== lastDay) {
        items.push(h("div", { class: "day", text: label }));
        lastDay = label;
      }
    };

    // `previo` es el ultimo mensaje con burbuja: decide si el siguiente abre grupo. Una nota
    // de sistema o un separador de dia rompen el grupo, porque visualmente ya lo separan.
    let previo = null;

    // Saludo local (no persistido): es el INICIO de la conversacion, asi que va ARRIBA del
    // todo y una sola vez. Antes se re-inyectaba al final en cada apertura del panel y, a
    // mitad de una charla, se leia como si el bot volviera a saludar de la nada.
    // Dos condiciones:
    //   - solo en el hilo del bot (un caso con asesor no se presenta como Subastin);
    //   - solo con el historial COMPLETO cargado (`!state.hasMore`): encima de una pagina
    //     parcial estaria mintiendo sobre donde empezo la conversacion.
    // Con el hilo vacio espera al fade de la apertura (`greetingVisible`); con historial ya
    // es contenido viejo y se dibuja de una.
    const hayHistorial = state.messages.length > 0;
    // Skeleton (pedido de Aaron, 2026-09-03): con el hilo vacio, mientras el saludo todavia no
    // "llego" o el servidor no devolvio la conversacion (primer sondeo, historial en camino),
    // dos burbujas fantasma del lado del bot. Nunca junto al saludo: uno u otro.
    const esqueleto =
      !hayHistorial && !state.hasMore && (!state.greetingVisible || !state.conversation) &&
      (state.conversation === null || isThread(state.conversation));
    if (esqueleto) {
      // Carga del hilo: un spinner comun, chico y centrado (Aaron, 2026-09-03). Se probaron
      // un skeleton y el orbe liquido; el orbe es el estado "Subastin esta pensando" y aqui
      // no piensa nadie, solo se esta leyendo el estado.
      items.push(
        h(
          "div",
          { class: "thread-loading", role: "status", "aria-label": TEXT.loadingThread },
          h("span", { class: "spinner" })
        )
      );
    }
    if (!esqueleto && isThread(state.conversation) && !state.hasMore && (hayHistorial || state.greetingVisible)) {
      items.push(
        renderBubble(
          {
            sender_type: SENDER.BOT,
            content: name ? TEXT.greetingAuth(name) : TEXT.greetingAnon,
            created_at: null,
            // Clave estable: `firstRenderOf` lo anima UNA vez por carga de pagina, no en
            // cada render ni en cada apertura del panel.
            client_message_id: "greeting",
            isGreeting: true,
          },
          true
        )
      );
    }

    if (state.hasMore) {
      items.push(
        h("button", {
          class: "link older",
          type: "button",
          text: state.loadingOlder ? TEXT.sending : TEXT.olderMessages,
          onclick: loadOlder,
        })
      );
    }
    const ultimo = lastMessage();
    // D-030: con un formulario a la vista no hay botones de pregunta ni compositor.
    const form = visibleForm();
    for (const message of state.messages) {
      const diaAntes = lastDay;
      pushDay(message.created_at);
      if (message.sender_type === SENDER.SYSTEM || message.message_type === MESSAGE_TYPE.SYSTEM) {
        items.push(renderSystemEvent(message));
        previo = null;
        continue;
      }
      const cambioDeDia = lastDay !== diaAntes;
      items.push(renderBubble(message, cambioDeDia || !sameGroup(previo, message)));
      previo = message;
      // Quick replies (D-028), preguntas hermanas (D-030) y enlaces (D-031): SOLO bajo el
      // ultimo mensaje del hilo y sin envios en vuelo — en cuanto el usuario responde (click
      // o texto), los botones desaparecen del render.
      if (message === ultimo && state.pending.size === 0 && !form) {
        const botones = renderQuickReplies(message) || renderRelatedQuestions(message) || renderLinks(message);
        if (botones) items.push(botones);
      }
    }
    for (const [clientMessageId, draft] of state.pending) {
      if (draft.conversationId && draft.conversationId !== state.activeId) continue;
      pushDay(draft.createdAt);
      const propio = { sender_type: SENDER.USER, created_at: draft.createdAt };
      items.push(renderPending(clientMessageId, draft, !sameGroup(previo, propio)));
      previo = propio;
    }
    const typing = renderTyping();
    if (typing) items.push(typing);
    // D-030: el formulario de asesor (del bot o del badge) va al final del hilo y, mientras
    // este a la vista, el compositor se retira: lo que se escribe es el formulario.
    if (form) items.push(renderHandoffForm(form.spec, form.key));
    state.repliesReturn = false; // el fade de vuelta de los botones es de un solo render

    return h(
      "div",
      { class: "screen messages" },
      renderThreadHeader(),
      renderBanner(),
      renderAnonBanner(),
      h(
        "div",
        { class: "thread-wrap" },
        h(
          "div",
          {
            class: "thread",
            role: "log",
            "aria-live": "polite",
            onscroll: (event) => onThreadScroll(event.currentTarget),
          },
          items
        ),
        state.unseenBelow
          ? h(
              "button",
              {
                class: "jump",
                type: "button",
                onclick: () => {
                  const hilo = panelEl.querySelector(".thread");
                  if (hilo) hilo.scrollTo({ top: hilo.scrollHeight, behavior: "smooth" });
                  scrollToBottomNext();
                  render();
                },
              },
              ICON.chevron(),
              h("span", { text: String(state.unseenBelow) })
            )
          : null
      ),
      state.conversation && state.conversation.status === STATUS.CLOSED
        ? renderClosedBar()
        : form
          ? null
          : renderComposer()
    );
  }

  function statusLabel(conv) {
    if (!conv) return null;
    if (conv.status === STATUS.PENDING_ADVISOR) return TEXT.statusPending;
    if (conv.status === STATUS.IN_ATTENTION) return TEXT.statusAttending;
    if (conv.status === STATUS.CLOSED) return TEXT.statusClosed;
    return null;
  }

  function conversationLabel(conv) {
    if (isThread(conv)) return TEXT.threadName;
    return conv.title || TEXT.navMessages;
  }

  /** Cabecera del hilo: Subastín "en linea" en el hilo del bot (gris si no hay conexion);
   *  en un caso, su asunto y en que esta (esperando asesor, atendido, cerrado). */
  function renderThreadHeader() {
    const conv = state.conversation;
    const caso = !isThread(conv);
    const estado = statusLabel(conv);
    const back = () => (isAnonymous() ? setView("home") : setView("inbox"));
    const subtitulo = estado
      ? h("small", { class: "status-line", text: estado })
      : h(
          "small",
          { class: "status-line" },
          h("i", { class: "status-dot" + (state.offline ? " is-off" : ""), "aria-hidden": "true" }),
          state.offline ? TEXT.offlineStatus : TEXT.agentStatus
        );
    return h(
      "header",
      { class: "bar" },
      iconButton(TEXT.back, ICON.back(), back),
      caso ? null : botAvatar("avatar", true),
      h("div", { class: "bar-title" }, h("strong", { text: conversationLabel(conv) }), subtitulo),
      closeButton()
    );
  }

  /** Caso cerrado (D-029): de solo lectura; se vuelve al hilo con Subastín. */
  function renderClosedBar() {
    return h(
      "div",
      { class: "closed-bar" },
      h("span", { text: TEXT.closedCase }),
      h("button", { class: "qr", type: "button", text: TEXT.backToBot, onclick: openThread })
    );
  }

  function shortWhen(iso) {
    const label = dayLabel(iso);
    return label === TEXT.today ? formatTime(iso) : label;
  }

  /** Lista de conversaciones del autenticado (D-029): el hilo con Subastín arriba y debajo
   *  los casos con asesor, el mas reciente primero, con su estado. */
  function renderInbox() {
    const thread = state.conversations.find((c) => c.kind !== KIND.CASE) || null;
    const cases = state.conversations.filter((c) => c.kind === KIND.CASE);
    const row = (conv, primary, secondary, avatar) =>
      h(
        "li",
        {},
        h(
          "button",
          { type: "button", class: "inbox-row", onclick: () => switchConversation(conv.conversation_id) },
          avatar,
          h(
            "div",
            { class: "inbox-meta" },
            h(
              "div",
              { class: "inbox-top" },
              h("span", { class: "inbox-title", text: primary }),
              conv.last_message_at ? h("small", { class: "inbox-time", text: shortWhen(conv.last_message_at) }) : null
            ),
            h("span", { class: "inbox-preview", text: secondary || "" })
          ),
          statusLabel(conv)
            ? h("span", {
                class:
                  "chip" +
                  (conv.status === STATUS.CLOSED ? " chip-closed" : conv.status === STATUS.IN_ATTENTION ? " chip-live" : ""),
                text: statusLabel(conv),
              })
            : ICON.chevron()
        )
      );
    return h(
      "div",
      { class: "screen inbox" },
      h(
        "header",
        { class: "bar bar-plain" },
        h("div", { class: "bar-title" }, h("strong", { text: TEXT.inboxTitle })),
        closeButton()
      ),
      h(
        "div",
        { class: "help-body" },
        renderBanner(),
        h(
          "ul",
          { class: "list list-inbox" },
          thread ? row(thread, TEXT.threadName, thread.last_message_preview || TEXT.sendUsSub, botAvatar("avatar", false)) : null,
          cases.map((c) => row(c, c.title || TEXT.navMessages, c.last_message_preview, h("span", { class: "inbox-icon" }, ICON.messages())))
        ),
        cases.length ? null : h("p", { class: "muted", text: TEXT.noCases })
      ),
      renderNav()
    );
  }
