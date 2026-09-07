
  function viewDepth(view, article) {
    return (VIEW_ORDER[view] || 0) + (article ? 0.5 : 0);
  }

  /** Cruza dos pantallas: la saliente se va hacia un lado mientras la entrante llega del otro.
   *  Las dos conviven un instante (la saliente en position:absolute sobre el panel) y la vieja
   *  se retira al terminar. El timeout es la red de seguridad: si el navegador no dispara
   *  animationend (pestaña oculta, prefers-reduced-motion), la pantalla saliente igual se va. */
  function crossfade(outgoing, incoming, direction) {
    const salida = direction > 0 ? "to-left" : "to-right";
    const entrada = direction > 0 ? "from-right" : "from-left";
    outgoing.classList.add("is-leaving", salida);
    incoming.classList.add("is-entering", entrada);
    panelEl.appendChild(incoming);
    const quitar = () => outgoing.isConnected && outgoing.remove();
    outgoing.addEventListener("animationend", quitar, { once: true });
    setTimeout(quitar, 420);
  }


  function render() {
    if (!root) return;
    updateLauncher();
    panelEl.classList.toggle("is-open", state.open);
    panelEl.setAttribute("aria-hidden", state.open ? "false" : "true");
    if (!state.open) return;
    ensureLottie();
    ensureOrbGpu(); // el orbe WebGPU calienta desde que se abre el panel
    // D-030: si va a aparecer un formulario de asesor y el compositor esta en pantalla, el
    // cambio no es de golpe. Primero, sobre el DOM vivo, los botones de pregunta se van con
    // un fade y el compositor se pliega hacia abajo (su altura baja a cero, asi el hilo crece
    // y el formulario "empuja"); recien al terminar se dibuja el estado nuevo. Mientras dura,
    // cualquier otro render se pospone: reemplazar el DOM a mitad de la animacion la corta.
    if (state.formEntering) return;
    // `dibujando` corta la recursion: el callback vuelve a entrar a render() y, como el
    // compositor SIGUE en el DOM (todavia no se redibujo), sin esta bandera se pediria otra
    // vez la misma animacion, para siempre. Con `prefers-reduced-motion` el callback es
    // sincrono y el desborde de pila era inmediato: el formulario no llegaba a aparecer
    // (Windows con "efectos de animacion" apagados lo activa; visto el 2026-09-03).
    if (!dibujandoFormulario && state.view === "messages" && visibleForm() &&
        panelEl.querySelector(".screen:not(.is-leaving) .composer")) {
      state.formEntering = true;
      fadeOutReplies();
      collapseComposer(() => {
        state.formEntering = false;
        dibujandoFormulario = true;
        try {
          render();
        } finally {
          dibujandoFormulario = false;
        }
      });
      return;
    }
    // Se lee ANTES de dibujar: renderComposer consume esta bandera de un solo uso.
    const composerReturning = state.composerReturn;
    const view =
      state.view === "messages"
        ? renderMessages()
        : state.view === "inbox"
          ? renderInbox()
          : state.view === "help"
            ? renderHelp()
            : renderHome();
    // La pantalla entra animada SOLO al cambiar de vista (o al abrir el panel). Si se animara
    // en cada render, la pantalla entera parpadearia cada vez que llega un mensaje.
    const viewKey = state.view + (state.helpArticle ? ":" + (state.helpArticle.id || "") : "");
    const changedView = viewKey !== lastViewKey && lastViewKey !== null;
    // Direccion del cruce segun el orden de la barra inferior: ir a la derecha entra desde la
    // derecha. Un articulo de ayuda cuenta como "mas adentro" que su lista.
    const direction = Math.sign(viewDepth(state.view, state.helpArticle) - lastViewDepth) || 1;
    if (viewKey !== lastViewKey) {
      if (!changedView) view.classList.add("is-entering");
      lastViewKey = viewKey;
      lastViewDepth = viewDepth(state.view, state.helpArticle);
    }
    const current = panelEl.querySelector(".screen:not(.is-leaving)");
    const previousScroll = current ? current.querySelector(".thread") : null;
    const wasAtBottom =
      previousScroll && previousScroll.scrollHeight - previousScroll.scrollTop - previousScroll.clientHeight < 40;
    const previousTop = previousScroll ? previousScroll.scrollTop : 0;
    const previousHeight = previousScroll ? previousScroll.scrollHeight : 0;
    // El re-render reemplaza el compositor: sin rescatar el borrador, un mensaje del bot que
    // llega mientras el usuario escribe le borraria lo tecleado (RF-037 protege el envio, no
    // el texto sin enviar).
    // OJO con el selector: tiene que ser el textarea DEL COMPOSITOR. Con `textarea` a secas
    // agarraba el primero de la pantalla, que con el formulario de asesor abierto es su campo
    // "Cuentanos que paso": al enviarlo, ese texto reaparecia dentro del cuadro de mensajes
    // (Aaron, 2026-09-03).
    const previousComposer = current ? current.querySelector(".composer textarea") : null;
    const draft = previousComposer ? previousComposer.value : "";
    const caret = previousComposer ? previousComposer.selectionStart : 0;
    // El foco va al compositor solo si YA lo tenia, al entrar a la vista de mensajes o cuando
    // vuelve tras un formulario. Enfocarlo en CADA render —o sea, en cada sondeo que trae
    // algo— le robaba el foco a la pagina de VMC y a un boton de pregunta recien tabulado, y
    // en movil levantaba el teclado solo (auditoria 2026-09-06).
    const composerHadFocus = previousComposer !== null && root.activeElement === previousComposer;

    if (changedView && current) crossfade(current, view, direction);
    else panelEl.replaceChildren(view);

    mountAnimatedAvatars();
    const thread = view.querySelector(".thread");
    if (thread) {
      const primeraVez = previousScroll === null;
      if (primeraVez || wasAtBottom || state.stickToBottom) {
        // Un mensaje que LLEGA (bot o asesor) se lee desde arriba: su inicio se alinea con el
        // borde superior del hilo, deslizando suave (pedido de Aaron, 2026-09-03). Si es corto
        // y no hay contenido para llegar ahi, el navegador se queda en el fondo, que es lo
        // mismo. Lo propio, y la primera apertura, siguen aterrizando abajo.
        const nuevo = primeraVez ? null : view.querySelector(".row.is-new:not(.row-mine):not(.is-greeting)");
        if (nuevo) {
          const top = nuevo.getBoundingClientRect().top - thread.getBoundingClientRect().top + thread.scrollTop - 6;
          state.autoScrollUntil = Date.now() + 900;
          thread.scrollTo({ top: Math.max(0, top), behavior: reducedMotion() ? "auto" : "smooth" });
        } else {
          thread.scrollTop = thread.scrollHeight;
        }
        scrollToBottomNext();
      } else {
        // El usuario estaba leyendo mas arriba: se respeta su punto exacto. Si el contenido
        // crecio por arriba (paginacion hacia atras), se compensa para que no se le mueva.
        const crecioArriba = thread.scrollHeight - previousHeight;
        thread.scrollTop = previousTop + (crecioArriba > 0 && previousTop < 40 ? crecioArriba : 0);
      }
    }
    const composer = view.querySelector(".composer textarea");
    if (composer && state.view === "messages") {
      if (draft) {
        composer.value = draft;
        try {
          composer.setSelectionRange(caret, caret);
        } catch (_) {
          /* navegadores que no permiten mover el caret sin foco */
        }
        autoGrow(composer);
      }
      if (composerHadFocus || changedView || previousScroll === null || composerReturning) {
        composer.focus({ preventScroll: true });
      }
    }
  }

  /** Boton redondo con icono (cerrar, volver): mismo markup en las cuatro cabeceras. */
  function iconButton(label, icon, onclick) {
    return h("button", { class: "icon-btn", type: "button", "aria-label": label, onclick }, icon);
  }

  function closeButton() {
    return iconButton(TEXT.close, ICON.close(), () => setOpen(false));
  }

  /** El compositor crece con el texto hasta el tope y solo entonces hace scroll interno.
   *  La barra se enciende AQUI y no en el CSS: con `overflow-y: auto` fijo, el navegador la
   *  pinta en cuanto el contenido pasa del alto actual —o sea, al primer salto de linea— y se
   *  ve como un defecto. Mientras el textarea pueda crecer, no hay nada que desbordar. */
  function autoGrow(textarea) {
    textarea.style.height = "auto";
    const alto = Math.min(textarea.scrollHeight, CONFIG.composerMaxPx);
    textarea.style.height = alto + "px";
    textarea.style.overflowY = textarea.scrollHeight > CONFIG.composerMaxPx ? "auto" : "hidden";
  }

  /** El usuario esta "abajo" si le faltan menos de 40 px: ahi el hilo sigue cada mensaje nuevo.
   *  Si subio a leer, se respeta su posicion y los mensajes que llegan se cuentan en la pildora. */
  function onThreadScroll(hilo) {
    // El deslizamiento que alinea un mensaje nuevo arriba no es el usuario leyendo: mientras
    // dura, no cambia el "sigue abajo" (si lo cambiara, el siguiente mensaje ya no alinearia).
    if (Date.now() < state.autoScrollUntil) return;
    const abajo = hilo.scrollHeight - hilo.scrollTop - hilo.clientHeight < 40;
    if (abajo === state.stickToBottom) return;
    state.stickToBottom = abajo;
    if (abajo && state.unseenBelow) {
      state.unseenBelow = 0;
      render();
    }
  }

  // El boton flotante NO se recrea en cada render: si se reemplazara, la transicion de hover
  // se cortaria cada vez que llega un mensaje. Solo se actualizan icono, estado y contador.
  function updateLauncher() {
    if (!launcherEl) return; // desmontado
    const open = state.open;
    launcherEl.classList.toggle("is-open", open);
    launcherEl.setAttribute("aria-label", open ? TEXT.minimize : TEXT.open);
    launcherEl.setAttribute("aria-expanded", open ? "true" : "false");
    launcherIconEl.replaceChildren(open ? ICON.minimize() : ICON.chat());

    const showBadge = !open && state.unread > 0;
    launcherBadgeEl.hidden = !showBadge;
    const label = String(state.unread);
    if (showBadge && launcherBadgeEl.textContent !== label) {
      launcherBadgeEl.textContent = label;
      // Reinicia la animacion de aparicion SOLO cuando el numero cambia (sin el reflow, el
      // navegador no vuelve a lanzar la misma animacion).
      launcherBadgeEl.classList.remove("is-bump");
      void launcherBadgeEl.offsetWidth;
      launcherBadgeEl.classList.add("is-bump");
    }
  }

  /** Marca un id como ya dibujado y dice si es la primera vez (para animarlo una sola vez). */
  function firstRenderOf(key) {
    if (!key || state.seen.has(key)) return false;
    state.seen.add(key);
    return true;
  }

  /** El bot esta callado si el ultimo evento de sistema fue un handoff o la toma de un asesor
   *  (D-007: no se re-enciende solo). Ahi no se promete "escribiendo": responde una persona. */
  function botSilent() {
    if (state.conversation) return !state.conversation.bot_enabled;
    for (let i = state.messages.length - 1; i >= 0; i -= 1) {
      const message = state.messages[i];
      if (message.sender_type !== SENDER.SYSTEM && message.message_type !== MESSAGE_TYPE.SYSTEM) continue;
      return message.content === "HANDOFF_REQUESTED" || message.content === "ADVISOR_ASSIGNED";
    }
    return false;
  }

  function displayName() {
    return state.session && state.session.userName ? state.session.userName : null;
  }

  function renderNav() {
    const activo = (key) => state.view === key || (key === "messages" && state.view === "inbox");
    const item = (key, label, icon) =>
      h(
        "button",
        {
          class: "nav-item" + (activo(key) ? " is-active" : ""),
          type: "button",
          onclick: () => (key === "messages" ? openMessagesTab() : setView(key)),
        },
        icon,
        h("span", { text: label })
      );
    return h(
      "nav",
      { class: "nav" },
      item("home", TEXT.navHome, ICON.home()),
      item("messages", TEXT.navMessages, ICON.messages()),
      item("help", TEXT.navHelp, ICON.help())
    );
  }

  function renderBanner() {
    if (state.identityError) {
      return h(
        "div",
        { class: "banner banner-error" },
        h("p", { text: TEXT.identityError }),
        h("button", {
          class: "link",
          type: "button",
          text: TEXT.continueAnon,
          onclick: () => {
            state.forceAnonymous = true;
            reset(); // nada del intento fallido (ni de un usuario anterior) sigue en pantalla
            boot();
          },
        })
      );
    }
    if (state.offline) return h("div", { class: "banner banner-warn", text: TEXT.offline });
    return null;
  }

  function renderHome() {
    const name = displayName();
    const articles = HELP_CENTER.collections.flatMap((c) => c.articles).slice(0, 4);
    return h(
      "div",
      { class: "screen home" },
      h(
        "header",
        { class: "home-header" },
        h(
          "div",
          { class: "home-top" },
          h("div", { class: "brand" }, brandLogo()),
          botAvatar("avatar avatar-lg", true)
        ),
        h("h1", { text: name ? TEXT.homeTitleAuth(name) : TEXT.homeTitleAnon })
      ),
      h(
        "div",
        { class: "home-body" },
        renderBanner(),
        h(
          "button",
          { class: "card card-cta", type: "button", onclick: openThread },
          h("div", {}, h("strong", { text: TEXT.sendUs }), h("small", { text: TEXT.sendUsSub })),
          h("span", { class: "cta-icon" }, ICON.send())
        ),
        h(
          "div",
          { class: "card" },
          h(
            "button",
            { class: "search", type: "button", onclick: () => setView("help") },
            h("span", { text: TEXT.searchHelp }),
            ICON.search()
          ),
          articles.length
            ? h(
                "ul",
                { class: "list" },
                articles.map(articleRow)
              )
            : h("p", { class: "muted", text: TEXT.noArticles })
        )
      ),
      renderNav()
    );
  }
