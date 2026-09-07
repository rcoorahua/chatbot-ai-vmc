
  function renderComposer() {
    const textarea = h("textarea", {
      rows: "1",
      placeholder: TEXT.composer,
      "aria-label": TEXT.composer,
      // El tope real del servidor (D-005), no uno de transporte: cortar aqui evita que el
      // usuario escriba un parrafo que la API va a rechazar con 422.
      maxlength: String(state.maxChars),
    });
    // El contador aparece recien cerca del limite: mostrarlo siempre es ruido en un chat.
    const contador = h("span", { class: "counter", hidden: true });
    const pintarContador = () => {
      const usado = textarea.value.length;
      const cerca = usado >= state.maxChars * 0.8;
      contador.hidden = !cerca;
      if (cerca) {
        contador.textContent = usado + " / " + state.maxChars;
        contador.classList.toggle("is-full", usado >= state.maxChars);
      }
    };
    // Sin texto no hay nada que enviar: el boton se apaga para que el estado sea visible
    // ANTES del click, en vez de un click que no hace nada (sendMessage ya ignora el vacio).
    const sendBtn = h(
      "button",
      { class: "send", type: "submit", "aria-label": TEXT.send, disabled: "" },
      ICON.send()
    );
    const syncSend = () => {
      sendBtn.disabled = textarea.value.trim() === "";
    };
    const submit = () => {
      const value = textarea.value;
      textarea.value = "";
      autoGrow(textarea);
      pintarContador();
      syncSend();
      sendMessage(value);
    };
    textarea.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        submit();
      }
    });
    textarea.addEventListener("input", () => {
      autoGrow(textarea);
      pintarContador();
      syncSend();
    });
    // Adjuntos (F6, bloqueado por D-015) y emojis todavia no existen: los botones estan para
    // que el compositor tenga la anatomia final, pero deshabilitados — nada de controles que
    // parecen vivos y no hacen nada al click.
    const tool = (icon, label) =>
      h(
        "button",
        { class: "tool", type: "button", disabled: "", "aria-label": label,
          title: `${label} — ${TEXT.soon}` },
        icon
      );
    // Vuelve subiendo cuando un formulario acaba de retirarse (una sola vez): la animacion
    // corre sobre el elemento ya montado, en el frame siguiente al render.
    const returning = state.composerReturn;
    state.composerReturn = false;
    const composerEl = h(
      "form",
      {
        class: "composer",
        onsubmit: (event) => {
          event.preventDefault();
          submit();
        },
      },
      h(
        "div",
        { class: "composer-box" },
        h("div", { class: "composer-field" }, textarea, contador),
        h(
          "div",
          { class: "composer-actions" },
          tool(ICON.clip(), TEXT.attach),
          tool(ICON.smile(), TEXT.emoji),
          sendBtn
        )
      )
    );
    if (returning) requestAnimationFrame(() => expandComposer(composerEl));
    return composerEl;
  }

  function renderHelp() {
    if (state.helpArticle) {
      const article = state.helpArticle;
      return h(
        "div",
        { class: "screen help" },
        h(
          "header",
          { class: "bar" },
          iconButton(TEXT.back, ICON.back(), () => { state.helpArticle = null; render(); }),
          h("div", { class: "bar-title" }, h("strong", { text: article.title })),
          closeButton()
        ),
        h("article", { class: "article" }, (article.body || []).map((paragraph) => h("p", {}, textWithLinks(paragraph)))),
        renderNav()
      );
    }
    return h(
      "div",
      { class: "screen help" },
      h(
        "header",
        { class: "bar bar-plain" },
        h("div", { class: "bar-title" }, h("strong", { text: TEXT.helpTitle })),
        closeButton()
      ),
      h(
        "div",
        { class: "help-body" },
        h("div", { class: "help-intro" }, h("strong", { text: HELP_CENTER.title || TEXT.helpCenter }), h("small", { text: TEXT.helpCenterSub })),
        h(
          "ul",
          { class: "list list-collections" },
          HELP_CENTER.collections.map((collection) =>
            h(
              "li",
              {},
              h(
                "button",
                {
                  type: "button",
                  onclick: () => {
                    if (collection.articles.length === 1) openArticle(collection.articles[0]);
                  },
                },
                h("div", {}, h("span", { text: collection.title }), h("small", { text: collection.articles.length ? TEXT.articles(collection.articles.length) : TEXT.noArticles })),
                ICON.chevron()
              ),
              collection.articles.length > 1
                ? h(
                    "ul",
                    { class: "list list-nested" },
                    collection.articles.map(articleRow)
                  )
                : null
            )
          )
        )
      ),
      renderNav()
    );
  }

  /** Una fila de la lista de articulos: titulo + chevron, abre el articulo. */
  function articleRow(article) {
    return h(
      "li",
      {},
      h(
        "button",
        { type: "button", onclick: () => openArticle(article) },
        h("span", { text: article.title }),
        ICON.chevron()
      )
    );
  }

  function openArticle(article) {
    state.helpArticle = article;
    state.view = "help";
    render();
  }

  // ───────────────────────────────── Navegacion ─────────────────────────────────

  /** El saludo de una conversacion vacia "llega" ~420 ms despues (la transicion del panel
   *  dura .38 s): asi su fade se percibe como un mensaje y no como parte del panel. */
  function scheduleGreeting() {
    state.greetingVisible = false;
    clearTimeout(state.greetingTimer);
    state.greetingTimer = setTimeout(() => {
      state.greetingVisible = true;
      render();
    }, 420);
  }

  function setOpen(open) {
    if (!root) return; // desmontado
    // Al cerrar, si el foco estaba dentro del panel vuelve al boton que lo abrio: un dialogo
    // que se cierra y deja el foco en el vacio pierde al usuario de teclado o lector.
    const focusInside = !open && panelEl.contains(root.activeElement);
    state.open = open;
    // Al cerrar se olvida la vista dibujada para que al reabrir la pantalla vuelva a entrar
    // con su animacion, en lugar de aparecer de golpe.
    if (!open) lastViewKey = null;
    if (focusInside) launcherEl.focus({ preventScroll: true });
    if (open) {
      // Directo a mensajes (sin pasar por el home). Si un caso avanzo mientras estaba
      // cerrado, se abre en la lista para que se vea.
      state.view = !isAnonymous() && state.unread > 0 && hasOpenCase() ? "inbox" : "messages";
      state.unread = 0;
      scrollToBottomNext();
      // Conversacion recien empezada: el saludo entra DESPUES de que el panel termino de
      // abrir (transicion de .38s), asi su fade se percibe como un mensaje y no como parte
      // del panel. Con historial el saludo ya esta arriba y esto no cambia nada.
      if (state.messages.length === 0) scheduleGreeting();
      // Precarga del orbe WebGPU: compilar el shader recien cuando el usuario envia su primer
      // mensaje hacia que el indicador de "escribiendo" tardara en aparecer.
      ensureOrbGpu();
    }
    render();
    schedulePoll();
    if (open) boot();
  }

  function setView(view) {
    state.view = view;
    state.helpArticle = null;
    if (view === "messages" || view === "inbox") state.unread = 0;
    render();
    if (view === "messages") boot();
    if (view === "inbox") refreshList();
  }

  let booting = false;
  async function boot() {
    if (booting) return;
    booting = true;
    const gen = generation;
    try {
      await ensureSession();
      if (gen !== generation) return; // hubo un reset: el arranque nuevo ya va por su cuenta
      if (!isAnonymous() && !state.lastListAt) await fetchConversations();
      if (gen !== generation) return;
      await poll();
    } catch (error) {
      if (!isStale(error)) render();
    } finally {
      if (gen === generation) booting = false;
    }
  }
