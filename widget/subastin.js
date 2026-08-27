/*
 * Subastin — widget de chat embebible en VMC (RF-001, RF-004, RF-005, RF-036, RF-037, RF-038).
 *
 * Como se embebe (mismo esquema que Intercom, ver widget/README.md):
 *
 *   <script>
 *     window.subastinSettings = {
 *       apiUrl: "https://api.subastin.example",
 *       userJwt: "<JWT HS256 firmado por el SERVIDOR de VMC>"   // solo con sesion iniciada
 *     };
 *   </script>
 *   <script src="https://.../subastin.js" async></script>
 *
 * Decisiones de diseño:
 * - Un solo archivo sin build ni dependencias: lo puede servir cualquier CDN y probar cualquier
 *   HTML (widget/test.html). Todo el DOM vive en un Shadow DOM para que el CSS de VMC y el del
 *   widget no se pisen.
 * - Nunca se usa innerHTML: los mensajes los escriben usuarios y modelos, y se renderizan como
 *   texto (regla 5 de security-guidance). Los enlaces se detectan y se crean como nodos.
 * - Identidad: el widget NO lee cookies de VMC (son HttpOnly) ni manda un user_id suelto.
 *   Reenvia el JWT que VMC dejo en la pagina; el backend lo verifica y devuelve un token de
 *   sesion propio (core/auth.py). RNF-005.
 * - Sesion en sessionStorage: sobrevive a navegar entre paginas y se pierde al cerrar la
 *   pestaña. Para el anonimo eso ES la regla de negocio (RF-004: sin historial entre sesiones);
 *   para el autenticado es solo una cache, su conversacion vive en el servidor (D-003).
 * - Entrega en tiempo real por sondeo (TD-001): 2,5 s con el panel abierto, 15 s cerrado para
 *   la burbuja de no leidos, pausado con la pestaña oculta.
 * - Un mensaje se muestra como enviado SOLO cuando el backend confirma (RNF-003); si falla,
 *   queda en el navegador con "Reintentar" y el reintento reutiliza el mismo
 *   client_message_id para que el backend no lo duplique (RF-037/RF-038).
 */
(function () {
  "use strict";

  if (window.__subastinBooted) return;
  window.__subastinBooted = true;

  const settings = window.subastinSettings || {};
  const API_URL = String(settings.apiUrl || "").replace(/\/+$/, "");
  if (!API_URL) {
    console.error("[Subastin] falta window.subastinSettings.apiUrl; el widget no se carga");
    return;
  }

  const CONFIG = {
    pollOpenMs: 2500,
    pollClosedMs: 15000,
    requestTimeoutMs: 15000,
    storageKey: "subastin.session.v1",
    pageSize: 100,
  };

  // Textos de la interfaz (UI en español, datos en ingles — decision T7).
  const TEXT = {
    brand: "VMC Subastas",
    brandSub: "powered by SUBASTOP Co.",
    agent: "Subastín",
    agentSub: "Asistente virtual de VMC",
    greetingAuth: (name) => `¡Bienvenido a VMC Subastas ${name}! ¿Cómo te podemos ayudar hoy?`,
    greetingAnon:
      "¡Bienvenido Cazador de Ofertas! Somos VMC Subastas, tu Marketplace de confianza. " +
      "Estamos a tu disposición para cualquier consulta que tengas.",
    homeTitleAuth: (name) => `¡Bienvenido al Nuevo VMC ${name}! ¿Cómo podemos ayudarte?`,
    homeTitleAnon: "¡Bienvenido al Nuevo VMC! ¿Cómo podemos ayudarte?",
    sendUs: "Envíanos un mensaje",
    sendUsSub: "Solemos responder en unos minutos",
    searchHelp: "Buscar ayuda",
    navHome: "Inicio",
    navMessages: "Mensajes",
    navHelp: "Ayuda",
    ready: "Estamos listos para ayudarte",
    composer: "Escribe un mensaje…",
    send: "Enviar",
    sending: "Enviando…",
    failed: "No se pudo enviar",
    retry: "Reintentar",
    anonHint:
      "Estás chateando como visitante: tu historial no se conserva al cerrar la pestaña. " +
      "Inicia sesión en VMC para conservarlo y hablar con un asesor.",
    identityError:
      "No pudimos verificar tu sesión de VMC. Recarga la página; si el problema sigue, " +
      "puedes continuar como visitante.",
    continueAnon: "Continuar como visitante",
    offline: "Sin conexión con Subastín. Reintentando…",
    today: "Hoy",
    yesterday: "Ayer",
    helpTitle: "Ayuda",
    helpCenter: "Centro de Ayuda",
    helpCenterSub: "Toda la información que necesitas en un solo lugar",
    articles: (n) => (n === 1 ? "1 artículo" : `${n} artículos`),
    noArticles: "Artículos en preparación",
    back: "Volver",
    close: "Cerrar",
    open: "Abrir chat",
  };

  // Eventos de auditoria que llegan como mensajes SYSTEM (conversations/models.py SystemEvent)
  // y su texto en el hilo, al estilo de las notas de sistema de Intercom.
  const SYSTEM_EVENTS = {
    HANDOFF_REQUESTED: "Solicitaste hablar con un asesor",
    ADVISOR_ASSIGNED: "Un asesor se unió a la conversación",
    TICKET_OPENED: "Ticket abierto",
    TICKET_CLOSED: "Ticket cerrado",
    BOT_DISABLED: "Subastín dejó de responder mientras un asesor atiende tu caso",
    BOT_ENABLED: "Subastín vuelve a atenderte",
    CONVERSATION_CLOSED: "Conversación cerrada",
  };

  // TODO: el contenido real del centro de ayuda lo entrega VMC; por ahora solo la estructura
  // (colecciones vistas en Intercom). Cada articulo: { id, title, body: ["parrafo", ...] }.
  const HELP_CENTER = (settings.helpCenter && typeof settings.helpCenter === "object")
    ? settings.helpCenter
    : {
        title: "Centro de Ayuda Comprador",
        collections: [
          { id: "top", title: "Lo más consultado", articles: [] },
          { id: "registro", title: "El registro", articles: [] },
          { id: "billetera", title: "La billetera", articles: [] },
          { id: "visitas", title: "Las visitas", articles: [] },
          { id: "consignacion", title: "La consignación", articles: [] },
        ],
      };

  // ───────────────────────────────────── Estado ─────────────────────────────────────

  const state = {
    open: false,
    view: "home", // home | messages | help
    helpArticle: null,
    session: null, // { token, expiresAt, userType, userName, userId, conversationId }
    messages: [], // confirmados por el backend, en orden cronologico
    pending: new Map(), // client_message_id -> { content, status, createdAt }
    lastKey: null,
    unread: 0,
    identityError: false,
    forceAnonymous: false,
    offline: false,
    pollTimer: null,
    loading: false,
  };

  // ───────────────────────────────── Utilidades DOM ─────────────────────────────────

  function h(tag, attrs, ...children) {
    const el = document.createElement(tag);
    if (attrs) {
      for (const [key, value] of Object.entries(attrs)) {
        if (value === null || value === undefined || value === false) continue;
        if (key === "class") el.className = value;
        else if (key === "text") el.textContent = value;
        else if (key.startsWith("on")) el.addEventListener(key.slice(2), value);
        else el.setAttribute(key, value === true ? "" : String(value));
      }
    }
    for (const child of children.flat()) {
      if (child === null || child === undefined || child === false) continue;
      el.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
    }
    return el;
  }

  function svg(paths, size) {
    const ns = "http://www.w3.org/2000/svg";
    const el = document.createElementNS(ns, "svg");
    el.setAttribute("viewBox", "0 0 24 24");
    el.setAttribute("width", String(size || 22));
    el.setAttribute("height", String(size || 22));
    el.setAttribute("fill", "none");
    el.setAttribute("stroke", "currentColor");
    el.setAttribute("stroke-width", "1.8");
    el.setAttribute("stroke-linecap", "round");
    el.setAttribute("stroke-linejoin", "round");
    el.setAttribute("aria-hidden", "true");
    for (const d of paths) {
      const path = document.createElementNS(ns, "path");
      path.setAttribute("d", d);
      el.appendChild(path);
    }
    return el;
  }

  const ICON = {
    chat: () => svg(["M4 5h16v11H8l-4 4V5z"], 26),
    close: () => svg(["M6 6l12 12M18 6L6 18"], 22),
    home: () => svg(["M3 11l9-8 9 8v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1v-9z"]),
    messages: () => svg(["M4 5h16v11H8l-4 4V5z", "M8 9h8M8 12h5"]),
    help: () => svg(["M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z", "M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.7.4-1 .9-1 1.7", "M12 17h.01"]),
    send: () => svg(["M12 19V5", "M6 11l6-6 6 6"], 20),
    back: () => svg(["M15 18l-6-6 6-6"], 22),
    chevron: () => svg(["M9 6l6 6-6 6"], 18),
    search: () => svg(["M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16z", "M21 21l-4.3-4.3"], 18),
  };

  // Enlaces como nodos <a> (nunca HTML crudo). Solo http(s), con rel="noopener".
  function textWithLinks(text) {
    const fragment = document.createDocumentFragment();
    const pattern = /https?:\/\/[^\s<>"']+/g;
    let last = 0;
    let match;
    // SAFETY: es RegExp.prototype.exec sobre texto para encontrar URLs; no ejecuta comandos ni
    // codigo (no es child_process.exec). El resultado solo alimenta textContent y href.
    while ((match = pattern.exec(text)) !== null) {
      if (match.index > last) fragment.appendChild(document.createTextNode(text.slice(last, match.index)));
      fragment.appendChild(
        h("a", { href: match[0], target: "_blank", rel: "noopener noreferrer", text: match[0] })
      );
      last = match.index + match[0].length;
    }
    if (last < text.length) fragment.appendChild(document.createTextNode(text.slice(last)));
    return fragment;
  }

  function formatTime(iso) {
    const date = new Date(iso);
    return isNaN(date) ? "" : date.toLocaleTimeString("es-PE", { hour: "2-digit", minute: "2-digit" });
  }

  function dayLabel(iso) {
    const date = new Date(iso);
    if (isNaN(date)) return "";
    const today = new Date();
    const sameDay = (a, b) =>
      a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
    if (sameDay(date, today)) return TEXT.today;
    const yesterday = new Date(today);
    yesterday.setDate(today.getDate() - 1);
    if (sameDay(date, yesterday)) return TEXT.yesterday;
    return date.toLocaleDateString("es-PE", { day: "2-digit", month: "long", year: "numeric" });
  }

  function newClientMessageId() {
    // El patron que acepta la API es [A-Za-z0-9_-]{8,64}. randomUUID existe en contextos
    // seguros (https, localhost, file); si no, un id aleatorio simple.
    const raw = (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`)
      .replace(/[^A-Za-z0-9]/g, "");
    return `cli-${raw}`.slice(0, 64);
  }

  // ───────────────────────────────── Sesion y API ─────────────────────────────────

  function loadStoredSession() {
    try {
      const raw = sessionStorage.getItem(CONFIG.storageKey);
      return raw ? JSON.parse(raw) : null;
    } catch (_) {
      return null;
    }
  }

  function storeSession(session) {
    try {
      if (session) sessionStorage.setItem(CONFIG.storageKey, JSON.stringify(session));
      else sessionStorage.removeItem(CONFIG.storageKey);
    } catch (_) {
      /* modo privado o storage bloqueado: la sesion vive solo en memoria */
    }
  }

  // Solo para comparar con la sesion guardada; la verificacion real la hace el backend.
  function subjectOf(jwt) {
    try {
      const payload = JSON.parse(atob(jwt.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")));
      return String(payload.sub || payload.user_id || "");
    } catch (_) {
      return "";
    }
  }

  function wantsAuthenticated() {
    return Boolean(settings.userJwt) && !state.forceAnonymous;
  }

  async function request(method, path, body, token) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), CONFIG.requestTimeoutMs);
    const headers = { Accept: "application/json" };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    if (token) headers.Authorization = `Bearer ${token}`;
    try {
      const response = await fetch(API_URL + path, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: controller.signal,
      });
      const data = response.status === 204 ? null : await response.json().catch(() => null);
      if (!response.ok) {
        const error = new Error((data && data.detail) || `HTTP ${response.status}`);
        error.status = response.status;
        throw error;
      }
      state.offline = false;
      return data;
    } catch (error) {
      if (!error.status) state.offline = true; // red caida o timeout, no un rechazo del backend
      throw error;
    } finally {
      clearTimeout(timer);
    }
  }

  async function ensureSession() {
    if (state.session) return state.session;
    const wantAuth = wantsAuthenticated();
    const wantedUser = wantAuth ? subjectOf(settings.userJwt) : null;
    const stored = loadStoredSession();
    const stillValid =
      stored &&
      stored.expiresAt * 1000 > Date.now() + 60000 &&
      stored.userType === (wantAuth ? "AUTHENTICATED" : "ANONYMOUS") &&
      (!wantAuth || stored.userId === wantedUser);
    if (stillValid) {
      state.session = stored;
      return stored;
    }

    const payload = wantAuth ? { user_jwt: settings.userJwt } : {};
    let data;
    try {
      data = await request("POST", "/chat/sessions", payload);
    } catch (error) {
      if (wantAuth && error.status === 401) {
        // El JWT de VMC no paso. No se degrada a anonimo en silencio: el usuario decide.
        state.identityError = true;
        render();
      }
      throw error;
    }
    const session = {
      token: data.token,
      expiresAt: data.expires_at,
      userType: data.user.type,
      userName: data.user.name,
      userId: wantedUser,
      conversationId: data.conversation.conversation_id,
    };
    state.session = session;
    state.identityError = false;
    storeSession(session);
    return session;
  }

  function dropSession() {
    state.session = null;
    state.messages = [];
    state.pending.clear();
    state.lastKey = null;
    storeSession(null);
  }

  // Cualquier llamada autenticada: si la sesion caduco, se abre otra y se reintenta una vez.
  async function withSession(fn) {
    const session = await ensureSession();
    try {
      return await fn(session);
    } catch (error) {
      if (error.status !== 401) throw error;
      dropSession();
      return fn(await ensureSession());
    }
  }

  // ───────────────────────────────── Mensajes ─────────────────────────────────

  function upsertMessages(incoming) {
    let added = 0;
    const known = new Set(state.messages.map((m) => m.message_id));
    for (const message of incoming) {
      if (known.has(message.message_id)) continue;
      state.messages.push(message);
      known.add(message.message_id);
      added += 1;
      if (message.client_message_id) state.pending.delete(message.client_message_id);
      if (!state.lastKey || message.message_key > state.lastKey) state.lastKey = message.message_key;
    }
    if (added) state.messages.sort((a, b) => (a.message_key < b.message_key ? -1 : 1));
    return added;
  }

  async function poll() {
    if (state.loading) return;
    state.loading = true;
    try {
      const data = await withSession((session) =>
        request(
          "GET",
          `/chat/conversations/${session.conversationId}/messages?limit=${CONFIG.pageSize}` +
            (state.lastKey ? `&after=${encodeURIComponent(state.lastKey)}` : ""),
          undefined,
          session.token
        )
      );
      const before = state.messages.length;
      const added = upsertMessages(data.messages);
      if (added && before > 0 && !(state.open && state.view === "messages")) {
        state.unread += data.messages.filter((m) => m.sender_type !== "USER").length;
      }
      if (added || state.offline) render();
    } catch (_) {
      render(); // muestra el aviso de sin conexion si aplica
    } finally {
      state.loading = false;
      schedulePoll();
    }
  }

  function schedulePoll() {
    clearTimeout(state.pollTimer);
    if (document.visibilityState === "hidden") return; // se reanuda en visibilitychange
    const delay = state.open ? CONFIG.pollOpenMs : CONFIG.pollClosedMs;
    state.pollTimer = setTimeout(poll, delay);
  }

  function sendMessage(text) {
    const content = text.trim();
    if (!content) return;
    const clientMessageId = newClientMessageId();
    state.pending.set(clientMessageId, {
      content,
      status: "sending",
      createdAt: new Date().toISOString(),
    });
    render();
    deliver(clientMessageId);
  }

  async function deliver(clientMessageId) {
    const draft = state.pending.get(clientMessageId);
    if (!draft) return;
    draft.status = "sending";
    render();
    try {
      const data = await withSession((session) =>
        request(
          "POST",
          `/chat/conversations/${session.conversationId}/messages`,
          { client_message_id: clientMessageId, content: draft.content },
          session.token
        )
      );
      state.pending.delete(clientMessageId);
      upsertMessages([data.message]);
    } catch (error) {
      draft.status = "failed";
      draft.error = error.message;
    }
    render();
  }

  // ───────────────────────────────── Render ─────────────────────────────────

  let root; // shadow root
  let panelEl;
  let launcherEl;

  function render() {
    if (!root) return;
    launcherEl.replaceChildren(renderLauncher());
    panelEl.classList.toggle("is-open", state.open);
    panelEl.setAttribute("aria-hidden", state.open ? "false" : "true");
    if (!state.open) return;
    const view =
      state.view === "messages" ? renderMessages() : state.view === "help" ? renderHelp() : renderHome();
    const previousScroll = panelEl.querySelector(".thread");
    const wasAtBottom =
      previousScroll && previousScroll.scrollHeight - previousScroll.scrollTop - previousScroll.clientHeight < 40;
    panelEl.replaceChildren(view);
    const thread = panelEl.querySelector(".thread");
    if (thread && (wasAtBottom || previousScroll === null)) thread.scrollTop = thread.scrollHeight;
    const composer = panelEl.querySelector("textarea");
    if (composer && state.view === "messages") composer.focus({ preventScroll: true });
  }

  function renderLauncher() {
    return h(
      "button",
      {
        class: "launcher",
        type: "button",
        "aria-label": state.open ? TEXT.close : TEXT.open,
        onclick: () => setOpen(!state.open),
      },
      state.open ? ICON.close() : ICON.chat(),
      !state.open && state.unread > 0 ? h("span", { class: "badge", text: String(state.unread) }) : null
    );
  }

  function displayName() {
    return state.session && state.session.userName ? state.session.userName : null;
  }

  function renderNav() {
    const item = (key, label, icon) =>
      h(
        "button",
        {
          class: "nav-item" + (state.view === key ? " is-active" : ""),
          type: "button",
          onclick: () => setView(key),
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
            state.identityError = false;
            dropSession();
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
    const anonymous = !state.session || state.session.userType !== "AUTHENTICATED";
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
          h("div", { class: "brand" }, h("strong", { text: TEXT.brand }), h("small", { text: TEXT.brandSub })),
          h("div", { class: "avatar avatar-lg", text: "S", "aria-hidden": "true" })
        ),
        h("h1", { text: name ? TEXT.homeTitleAuth(name) : TEXT.homeTitleAnon })
      ),
      h(
        "div",
        { class: "home-body" },
        renderBanner(),
        h(
          "button",
          { class: "card card-cta", type: "button", onclick: () => setView("messages") },
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
                articles.map((article) =>
                  h(
                    "li",
                    {},
                    h(
                      "button",
                      { type: "button", onclick: () => openArticle(article) },
                      h("span", { text: article.title }),
                      ICON.chevron()
                    )
                  )
                )
              )
            : h("p", { class: "muted", text: TEXT.noArticles })
        ),
        anonymous ? h("p", { class: "hint", text: TEXT.anonHint }) : null
      ),
      renderNav()
    );
  }

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

    if (state.messages.length === 0) {
      // Saludo local (no persistido): el mismo texto con el que Intercom abria la conversacion.
      items.push(h("div", { class: "ready", text: TEXT.ready }));
      items.push(
        renderBubble({
          sender_type: "BOT",
          content: name ? TEXT.greetingAuth(name) : TEXT.greetingAnon,
          created_at: null,
        })
      );
    }

    for (const message of state.messages) {
      pushDay(message.created_at);
      if (message.sender_type === "SYSTEM" || message.message_type === "SYSTEM") {
        items.push(renderSystemEvent(message));
      } else {
        items.push(renderBubble(message));
      }
    }
    for (const [clientMessageId, draft] of state.pending) {
      pushDay(draft.createdAt);
      items.push(renderPending(clientMessageId, draft));
    }

    return h(
      "div",
      { class: "screen messages" },
      h(
        "header",
        { class: "bar" },
        h("button", { class: "icon-btn", type: "button", "aria-label": TEXT.back, onclick: () => setView("home") }, ICON.back()),
        h("div", { class: "avatar", text: "S", "aria-hidden": "true" }),
        h("div", { class: "bar-title" }, h("strong", { text: TEXT.agent }), h("small", { text: TEXT.agentSub })),
        h("button", { class: "icon-btn", type: "button", "aria-label": TEXT.close, onclick: () => setOpen(false) }, ICON.close())
      ),
      renderBanner(),
      h("div", { class: "thread", role: "log", "aria-live": "polite" }, items),
      renderComposer()
    );
  }

  function renderBubble(message) {
    const mine = message.sender_type === "USER";
    // El asesor firma con su nombre (metadata.sender_name, lo pone la API); si no viene, "Asesor".
    const who = message.sender_type === "ADVISOR" ? ((message.metadata && message.metadata.sender_name) || "Asesor") : TEXT.agent;
    return h(
      "div",
      { class: "row" + (mine ? " row-mine" : "") },
      !mine ? h("div", { class: "avatar avatar-sm", text: message.sender_type === "ADVISOR" ? "A" : "S", "aria-hidden": "true" }) : null,
      h(
        "div",
        { class: "bubble-wrap" },
        h("div", { class: "bubble" + (mine ? " bubble-mine" : "") }, textWithLinks(message.content || "")),
        h(
          "small",
          { class: "meta" },
          !mine ? `${who}` : "",
          !mine && message.created_at ? " · " : "",
          message.created_at ? formatTime(message.created_at) : ""
        )
      )
    );
  }

  function renderPending(clientMessageId, draft) {
    const failed = draft.status === "failed";
    return h(
      "div",
      { class: "row row-mine" },
      h(
        "div",
        { class: "bubble-wrap" },
        h("div", { class: "bubble bubble-mine" + (failed ? " bubble-failed" : " bubble-pending") }, textWithLinks(draft.content)),
        failed
          ? h(
              "small",
              { class: "meta meta-error" },
              TEXT.failed + " · ",
              h("button", { class: "link", type: "button", text: TEXT.retry, onclick: () => deliver(clientMessageId) })
            )
          : h("small", { class: "meta", text: TEXT.sending })
      )
    );
  }

  function renderSystemEvent(message) {
    const label = SYSTEM_EVENTS[message.content] || message.content || "";
    return h(
      "div",
      { class: "system", title: message.created_at ? formatTime(message.created_at) : "" },
      h("span", { text: label })
    );
  }

  function renderComposer() {
    const textarea = h("textarea", {
      rows: "1",
      placeholder: TEXT.composer,
      "aria-label": TEXT.composer,
      maxlength: "20000",
    });
    const submit = () => {
      const value = textarea.value;
      textarea.value = "";
      sendMessage(value);
    };
    textarea.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        submit();
      }
    });
    return h(
      "form",
      {
        class: "composer",
        onsubmit: (event) => {
          event.preventDefault();
          submit();
        },
      },
      textarea,
      h("button", { class: "send", type: "submit", "aria-label": TEXT.send }, ICON.send())
    );
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
          h("button", { class: "icon-btn", type: "button", "aria-label": TEXT.back, onclick: () => { state.helpArticle = null; render(); } }, ICON.back()),
          h("div", { class: "bar-title" }, h("strong", { text: article.title })),
          h("button", { class: "icon-btn", type: "button", "aria-label": TEXT.close, onclick: () => setOpen(false) }, ICON.close())
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
        h("button", { class: "icon-btn", type: "button", "aria-label": TEXT.close, onclick: () => setOpen(false) }, ICON.close())
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
                    collection.articles.map((article) =>
                      h("li", {}, h("button", { type: "button", onclick: () => openArticle(article) }, h("span", { text: article.title }), ICON.chevron()))
                    )
                  )
                : null
            )
          )
        )
      ),
      renderNav()
    );
  }

  function openArticle(article) {
    state.helpArticle = article;
    state.view = "help";
    render();
  }

  // ───────────────────────────────── Navegacion ─────────────────────────────────

  function setOpen(open) {
    state.open = open;
    if (open && state.view === "messages") state.unread = 0;
    render();
    schedulePoll();
    if (open) boot();
  }

  function setView(view) {
    state.view = view;
    state.helpArticle = null;
    if (view === "messages") state.unread = 0;
    render();
    if (view === "messages") boot();
  }

  let booting = false;
  async function boot() {
    if (booting) return;
    booting = true;
    try {
      await ensureSession();
      await poll();
    } catch (_) {
      render();
    } finally {
      booting = false;
    }
  }

  // ───────────────────────────────── Estilos ─────────────────────────────────

  const CSS = `
    :host { all: initial; }
    * { box-sizing: border-box; }
    .root { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; font-size: 14px; line-height: 1.45; color: #1f1f2e; }
    button { font: inherit; color: inherit; background: none; border: 0; cursor: pointer; padding: 0; }
    .launcher { position: fixed; right: 20px; bottom: 20px; width: 56px; height: 56px; border-radius: 50%; background: #3b2a8c; color: #fff; display: grid; place-items: center; box-shadow: 0 6px 20px rgba(24, 16, 64, .35); z-index: 2147483000; transition: transform .15s ease; }
    .launcher:hover { transform: scale(1.05); }
    .badge { position: absolute; top: -4px; right: -4px; min-width: 20px; height: 20px; padding: 0 6px; border-radius: 10px; background: #ff6a4d; color: #fff; font-size: 12px; font-weight: 600; display: grid; place-items: center; }
    .panel { position: fixed; right: 20px; bottom: 90px; width: 400px; height: min(704px, calc(100vh - 110px)); background: #fff; border-radius: 16px; box-shadow: 0 12px 48px rgba(24, 16, 64, .28); overflow: hidden; display: none; z-index: 2147483000; }
    .panel.is-open { display: block; }
    @media (max-width: 480px) { .panel { right: 0; bottom: 0; width: 100vw; height: 100vh; border-radius: 0; } .launcher { right: 16px; bottom: 16px; } }
    .screen { display: flex; flex-direction: column; height: 100%; background: #fff; }
    .home { background: linear-gradient(180deg, #3b2a8c 0 42%, #f4f4f7 42% 100%); }
    .home-header { padding: 22px 22px 6px; color: #fff; }
    .home-top { display: flex; align-items: center; justify-content: space-between; }
    .brand { display: flex; flex-direction: column; line-height: 1.2; }
    .brand strong { font-size: 18px; letter-spacing: .01em; }
    .brand small { font-size: 10px; opacity: .8; }
    .home-header h1 { margin: 26px 0 14px; font-size: 25px; font-weight: 700; line-height: 1.2; }
    .home-body { flex: 1; overflow-y: auto; padding: 0 16px 16px; display: flex; flex-direction: column; gap: 12px; }
    .card { background: #fff; border-radius: 12px; box-shadow: 0 2px 10px rgba(24, 16, 64, .10); padding: 14px 16px; text-align: left; width: 100%; }
    .card-cta { display: flex; align-items: center; justify-content: space-between; }
    .card-cta strong { display: block; font-size: 15px; }
    .card-cta small, .search { color: #5a5a6e; }
    .cta-icon { width: 34px; height: 34px; border-radius: 50%; background: #ff6a4d; color: #fff; display: grid; place-items: center; transform: rotate(90deg); }
    .search { display: flex; align-items: center; justify-content: space-between; width: 100%; padding: 6px 0; font-weight: 600; color: #1f1f2e; }
    .search svg { color: #ff6a4d; }
    .list { list-style: none; margin: 0; padding: 0; }
    .list li { border-top: 1px solid #ececf1; }
    .list li > button { display: flex; align-items: center; justify-content: space-between; width: 100%; padding: 12px 0; text-align: left; gap: 12px; }
    .list li > button small { display: block; color: #7a7a8c; font-size: 12px; }
    .list li > button svg { color: #ff6a4d; flex: none; }
    .list-nested { margin-left: 14px; }
    .muted { color: #7a7a8c; margin: 8px 0 0; font-size: 13px; }
    .hint { font-size: 12px; color: #5a5a6e; background: #fff7f5; border: 1px solid #ffd9cf; border-radius: 10px; padding: 10px 12px; margin: 0; }
    .banner { padding: 10px 16px; font-size: 13px; }
    .banner p { margin: 0 0 6px; }
    .banner-error { background: #fff1f0; color: #8a1c12; }
    .banner-warn { background: #fff8e6; color: #7a5200; }
    .link { color: #3b2a8c; text-decoration: underline; font-weight: 600; }
    .bar { display: flex; align-items: center; gap: 10px; padding: 12px 12px; border-bottom: 1px solid #ececf1; background: #fff; }
    .bar-plain { justify-content: space-between; padding: 14px 16px; }
    .bar-title { flex: 1; display: flex; flex-direction: column; line-height: 1.2; }
    .bar-title strong { font-size: 15px; }
    .bar-title small { color: #6a6a7e; font-size: 12px; }
    .icon-btn { width: 36px; height: 36px; border-radius: 50%; display: grid; place-items: center; color: #3a3a4e; }
    .icon-btn:hover { background: #f1f1f5; }
    .avatar { width: 36px; height: 36px; border-radius: 50%; background: #3b2a8c; color: #fff; font-weight: 700; display: grid; place-items: center; flex: none; }
    .avatar-lg { width: 42px; height: 42px; border: 2px solid rgba(255,255,255,.7); }
    .avatar-sm { width: 26px; height: 26px; font-size: 12px; align-self: flex-end; }
    .thread { flex: 1; overflow-y: auto; padding: 16px 14px; display: flex; flex-direction: column; gap: 10px; background: #fff; }
    .ready { text-align: center; color: #8a8a9c; font-size: 13px; margin-bottom: 4px; }
    .day { align-self: center; font-size: 11px; color: #8a8a9c; text-transform: uppercase; letter-spacing: .04em; margin: 6px 0 2px; }
    .row { display: flex; gap: 8px; max-width: 85%; }
    .row-mine { align-self: flex-end; flex-direction: row-reverse; }
    .bubble-wrap { display: flex; flex-direction: column; gap: 3px; }
    .row-mine .bubble-wrap { align-items: flex-end; }
    .bubble { background: #f1f1f4; color: #1f1f2e; border-radius: 16px 16px 16px 4px; padding: 10px 14px; white-space: pre-wrap; word-break: break-word; }
    .bubble-mine { background: #3b2a8c; color: #fff; border-radius: 16px 16px 4px 16px; }
    .bubble a { color: inherit; text-decoration: underline; }
    .bubble-pending { opacity: .6; }
    .bubble-failed { background: #b3261e; }
    .meta { font-size: 11px; color: #8a8a9c; }
    .meta-error { color: #b3261e; }
    .system { align-self: center; display: flex; align-items: center; gap: 10px; color: #8a8a9c; font-size: 12px; width: 100%; margin: 6px 0; }
    .system::before, .system::after { content: ""; flex: 1; height: 1px; background: #e2e2ea; }
    .composer { display: flex; align-items: flex-end; gap: 8px; padding: 10px 12px; border-top: 1px solid #ececf1; background: #fff; }
    .composer textarea { flex: 1; resize: none; border: 1px solid #e2e2ea; border-radius: 20px; padding: 10px 14px; font: inherit; max-height: 120px; outline: none; }
    .composer textarea:focus { border-color: #ff6a4d; box-shadow: 0 0 0 3px rgba(255,106,77,.18); }
    .send { width: 40px; height: 40px; border-radius: 50%; background: #3b2a8c; color: #fff; display: grid; place-items: center; flex: none; }
    .nav { display: flex; border-top: 1px solid #ececf1; background: #fff; }
    .nav-item { flex: 1; display: flex; flex-direction: column; align-items: center; gap: 2px; padding: 10px 0 12px; font-size: 12px; color: #6a6a7e; }
    .nav-item.is-active { color: #ff6a4d; font-weight: 600; }
    .help-body { flex: 1; overflow-y: auto; padding: 0 16px 16px; }
    .help-intro { display: flex; flex-direction: column; padding: 14px 0; }
    .help-intro small { color: #6a6a7e; }
    .article { flex: 1; overflow-y: auto; padding: 16px; }
    .article p { margin: 0 0 12px; }
  `;

  // ───────────────────────────────── Montaje ─────────────────────────────────

  function mount() {
    const host = document.createElement("div");
    host.id = "subastin-widget";
    document.body.appendChild(host);
    root = host.attachShadow({ mode: "open" });
    const style = document.createElement("style");
    style.textContent = CSS;
    const container = h("div", { class: "root" });
    launcherEl = h("div", {});
    panelEl = h("div", { class: "panel", role: "dialog", "aria-label": TEXT.agent, "aria-hidden": "true" });
    container.append(launcherEl, panelEl);
    root.append(style, container);

    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") poll();
      else clearTimeout(state.pollTimer);
    });

    render();
    boot();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount);
  else mount();

  // Superficie minima para que la pagina anfitriona abra el chat (p. ej. desde un boton).
  window.Subastin = {
    open: () => setOpen(true),
    close: () => setOpen(false),
    showMessages: () => {
      state.view = "messages";
      setOpen(true);
    },
  };
})();
