
  /** Tres puntos animados mientras se espera la respuesta. No se muestra si el bot esta
   *  apagado por un handoff: ahi la espera es de una persona y puede durar mucho. */
  function renderTyping() {
    clearTimeout(state.typingTimer);
    if (!state.typingSince || botSilent()) return null;
    const remaining = CONFIG.typingMaxMs - (Date.now() - state.typingSince);
    if (remaining <= 0) {
      state.typingSince = null;
      return null;
    }
    // Sin este temporizador el indicador se quedaria fijo: el sondeo solo re-renderiza cuando
    // llega un mensaje nuevo, y si no llega ninguno nadie lo retiraria.
    state.typingTimer = setTimeout(() => {
      state.typingSince = null;
      render();
    }, remaining);
    const orbe = liquidOrb(44);
    return h(
      "div",
      { class: "row row-typing is-first" },
      orbe
        ? h("div", { class: "bubble typing typing-orb", role: "status", "aria-label": TEXT.typing }, orbe)
        : h(
            "div",
            { class: "bubble typing", role: "status", "aria-label": TEXT.typing },
            h("i", {}),
            h("i", {}),
            h("i", {})
          )
    );
  }

  /** Quien "habla" en una burbuja. Agrupa por interlocutor, no por remitente exacto: dos
   *  mensajes seguidos del mismo asesor son un grupo; si cambia el asesor, empieza otro. */
  function speakerOf(message) {
    if (message.sender_type === SENDER.USER) return SENDER.USER;
    if (message.sender_type === SENDER.ADVISOR) {
      return "ADVISOR:" + ((message.metadata && message.metadata.sender_name) || "");
    }
    return SENDER.BOT;
  }

  // Dos mensajes del mismo interlocutor separados por mas de esto empiezan grupo nuevo, como
  // en WhatsApp: el salto de tiempo se ve, aunque hable la misma persona.
  const GROUP_GAP_MS = 5 * 60 * 1000;

  function sameGroup(previo, actual) {
    if (!previo || speakerOf(previo) !== speakerOf(actual)) return false;
    const a = Date.parse(previo.created_at || "");
    const b = Date.parse(actual.created_at || "");
    if (isNaN(a) || isNaN(b)) return true; // sin hora (saludo local): sigue el grupo
    return b - a <= GROUP_GAP_MS;
  }

  /** Una burbuja. `primero` marca el primer mensaje del grupo: es el unico que lleva cola y,
   *  si habla un asesor, el unico que muestra su nombre. El avatar y el nombre del bot NO se
   *  repiten por mensaje — eso vive en la cabecera, como en cualquier app de mensajeria. */
  function renderBubble(message, primero) {
    const mine = message.sender_type === SENDER.USER;
    const advisor = message.sender_type === SENDER.ADVISOR;
    // El propio mensaje ya se animo como borrador: se reusa su client_message_id para que la
    // version confirmada no vuelva a entrar deslizandose.
    const fresh = firstRenderOf(message.client_message_id || message.message_id || "greeting");
    const clases =
      "row" + (mine ? " row-mine" : "") + (primero ? " is-first" : "") + (fresh ? " is-new" : "") +
      (message.isGreeting ? " is-greeting" : "");
    const bubble = h(
      "div",
      { class: "bubble" + (mine ? " bubble-mine" : "") },
      advisor && primero
        ? h("span", {
            class: "bubble-who",
            text: (message.metadata && message.metadata.sender_name) || "Asesor",
          })
        : null,
      h("div", { class: "bubble-text" }, renderRichText(message.content || ""))
    );
    // La hora se mete en el ULTIMO bloque de texto para que flote al final de su linea (el
    // truco de WhatsApp); con el texto en bloques, puesta despues quedaria en una linea sola.
    if (message.created_at) {
      const stamp = h("span", { class: "stamp", text: formatTime(message.created_at) });
      const cuerpo = bubble.querySelector(".bubble-text");
      (cuerpo.lastElementChild || cuerpo).appendChild(stamp);
    }
    // D-030: la fuente de una respuesta con evidencia va DEBAJO de la burbuja ("Fuente: ..."),
    // no como URL dentro del texto ni como un boton que se confunda con las preguntas.
    const sources = renderSources(message);
    return h("div", { class: clases }, sources ? h("div", { class: "bubble-wrap" }, bubble, sources) : bubble);
  }

  /** Linea de fuente (RF-019): "Fuente: <titulo del articulo>" como enlace subrayado, bajo la
   *  burbuja. `metadata.sources` = [{title, url}], deduplicadas por el servidor. Se muestra
   *  el TITULO, nunca la URL: por larga que sea la direccion, el texto es corto y se corta
   *  con puntos suspensivos si no cabe; el `title` deja ver el completo al pasar el mouse. */
  function renderSources(message) {
    const sources = message.metadata && message.metadata.sources;
    if (message.sender_type !== SENDER.BOT || !Array.isArray(sources) || !sources.length) return null;
    const links = [];
    for (const source of sources) {
      if (!source || !isHttpUrl(source.url)) continue;
      const label = source.title || source.url;
      links.push(
        h(
          "a",
          {
            class: "source-link",
            href: source.url,
            target: "_blank",
            rel: "noopener noreferrer",
            title: label + " · " + source.url,
          },
          h("span", { class: "source-title", text: label }),
          ICON.link()
        )
      );
    }
    if (!links.length) return null;
    return h("div", { class: "sources" }, h("span", { class: "sources-label", text: TEXT.sourceLabel + ":" }), links);
  }

  function renderPending(clientMessageId, draft, primero) {
    const failed = draft.status === "failed";
    return h(
      "div",
      {
        class:
          "row row-mine" + (primero ? " is-first" : "") +
          (firstRenderOf(clientMessageId) ? " is-new" : ""),
      },
      h(
        "div",
        { class: "bubble-wrap" },
        h("div", { class: "bubble bubble-mine" + (failed ? " bubble-failed" : " bubble-pending") }, textWithLinks(draft.content)),
        failed
          ? h(
              "small",
              { class: "meta meta-error" },
              (draft.rateLimited ? TEXT.tooFast : TEXT.failed) + " · ",
              h("button", { class: "link", type: "button", text: TEXT.retry, onclick: () => deliver(clientMessageId) })
            )
          : h("small", { class: "meta", text: TEXT.sending })
      )
    );
  }

  /** Botones de respuesta rapida (D-028) bajo el mensaje del bot que los trae en metadata.
   *  El click manda el LABEL como texto del hilo mas el evento estructurado; el servidor
   *  valida accion/valor/version contra el paso vigente — aqui no se decide nada. */
  /** Los botones que un mensaje del bot trae en `metadata.interaction` (QUICK_REPLIES,
   *  RELATED_QUESTIONS o LINKS): el envoltorio con su animacion de entrada y, por opcion, el
   *  nodo que `build` devuelva (null = esa opcion no se dibuja). Antes eran tres funciones casi
   *  identicas que solo cambiaban en el tipo, la clase y el evento (auditoria 2026-09-06). */
  function renderOptions(message, type, { key, extraClass = "", returning = false, build }) {
    const interaction = message.metadata && message.metadata.interaction;
    if (!interaction || interaction.type !== type || message.sender_type !== SENDER.BOT) return null;
    if (!Array.isArray(interaction.options)) return null;
    const wrap = h("div", {
      class:
        "quick-replies" + extraClass +
        (firstRenderOf(key + ":" + message.message_id) ? " is-new" : "") +
        (returning && state.repliesReturn ? " is-returning" : ""),
    });
    for (const option of interaction.options) {
      const node = option ? build(option, interaction) : null;
      if (node) wrap.appendChild(node);
    }
    return wrap.childNodes.length ? wrap : null;
  }

  /** Un boton de respuesta: manda su etiqueta como texto y el evento estructurado con el. */
  function replyButton(className, label, event) {
    return h("button", { class: className, type: "button", onclick: () => sendMessage(label, event) }, label);
  }

  function renderQuickReplies(message) {
    return renderOptions(message, INTERACTION.QUICK_REPLIES, {
      key: "qr",
      returning: true,
      build: (option, interaction) =>
        option.label && option.value
          ? replyButton("qr", option.label, {
              action_id: interaction.action_id,
              value: option.value,
              flow_version: interaction.flow_version,
              source_message_id: message.message_id,
            })
          : null,
    });
  }

  /** Preguntas hermanas (D-030): las otras preguntas del articulo que acaba de responder,
   *  como botones bajo la respuesta. Sin estado: el clic manda la pregunta como texto mas el
   *  evento {action_id, value}; el servidor la resuelve contra la metadata de SU ultimo
   *  mensaje (la consulta viaja ahi, no en el clic) y la manda al RAG sin clasificador. */
  function renderRelatedQuestions(message) {
    return renderOptions(message, INTERACTION.RELATED_QUESTIONS, {
      key: "rq",
      extraClass: " related",
      returning: true,
      build: (option, interaction) => {
        if (!option.label || !option.value) return null;
        // El mensaje sugerido de asesor (kind = handoff, siempre el ultimo, D-031) va en color
        // solido: no es "otra pregunta", es la salida a una persona. Viaja como cualquier clic
        // (texto + evento) y el servidor lo reconoce por su `value`; aqui no se decide nada.
        const handoff = option.kind === "handoff";
        return replyButton("qr " + (handoff ? "qr-solid qr-handoff" : "qr-related"), option.label, {
          action_id: interaction.action_id,
          value: option.value,
          source_message_id: message.message_id,
        });
      },
    });
  }

  /** Enlaces (D-031): botones que abren una URL en otra pestaña, bajo el mensaje del bot que
   *  los trae en metadata (hoy, "Iniciar sesión" para el visitante). Solo http(s). */
  function renderLinks(message) {
    return renderOptions(message, INTERACTION.LINKS, {
      key: "lk",
      build: (option) =>
        option.label && isHttpUrl(option.url)
          ? h("a", { class: "qr qr-solid", href: option.url, target: "_blank", rel: "noopener noreferrer", text: option.label })
          : null,
    });
  }

  const ANON_BANNER_KEY = CONFIG.storageKey + ":anon-banner";

  /** Franja del visitante dentro del hilo (D-030/D-031): parte del widget, no un mensaje del
   *  bot (no ensucia el historial ni cuesta una fila). Se cierra una vez por pestaña. */
  function renderAnonBanner() {
    if (!isAnonymous() || state.anonBannerDismissed) return null;
    try {
      if (sessionStorage.getItem(ANON_BANNER_KEY)) return null;
    } catch (_) {
      /* sin storage: se muestra igual y se cierra con el flag en memoria */
    }
    // Se vuelve a filtrar aqui: la sesion puede venir de sessionStorage, no solo del servidor.
    const login = state.session && isHttpUrl(state.session.loginUrl) ? state.session.loginUrl : null;
    return h(
      "div",
      { class: "banner banner-anon" },
      h(
        "span",
        {},
        TEXT.anonBanner + " ",
        login ? h("a", { class: "link", href: login, target: "_blank", rel: "noopener noreferrer", text: TEXT.anonLogin }) : null
      ),
      h("button", {
        class: "link",
        type: "button",
        text: TEXT.anonBannerDismiss,
        onclick: () => {
          state.anonBannerDismissed = true;
          try {
            sessionStorage.setItem(ANON_BANNER_KEY, "1");
          } catch (_) {
            /* idem */
          }
          render();
        },
      })
    );
  }

  function renderSystemEvent(message) {
    const meta = message.metadata || {};
    let label = SYSTEM_EVENTS[message.content] || message.content || "";
    let action = null;
    if (message.content === "CASE_OPENED") {
      if (meta.case_id) {
        label = TEXT.caseOpenedFrom(meta.title);
        action = h("button", { class: "link", type: "button", text: TEXT.openCase, onclick: () => switchConversation(meta.case_id) });
      } else {
        label = TEXT.caseOpenedHere;
      }
    }
    return h(
      "div",
      {
        class: "system" + (firstRenderOf(message.message_id) ? " is-new" : ""),
        title: message.created_at ? formatTime(message.created_at) : "",
      },
      h("span", { text: label }),
      action
    );
  }
