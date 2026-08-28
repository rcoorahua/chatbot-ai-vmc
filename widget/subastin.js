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
    // Cuanto se muestra el indicador de "escribiendo" sin respuesta. Cubre con holgura el
    // debounce del backend (6 s) mas la llamada IA; pasado eso se retira en vez de mentir.
    typingMaxMs: 45000,
    // Alto maximo del compositor al crecer con el texto (luego hace scroll interno).
    composerMaxPx: 132,
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
    typing: "Subastín está escribiendo",
    failed: "No se pudo enviar",
    // 429 (RF-014 / D-005): reintentar de inmediato solo empeora la rafaga, asi que el texto
    // pide esperar y el boton de reintentar sigue disponible por si el usuario insiste.
    tooFast: "Vas muy rapido. Espera un momento",
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
    // Ids ya dibujados alguna vez: el panel se re-renderiza entero cuando llega un mensaje, y
    // sin esta marca la animacion de entrada se repetiria en TODAS las burbujas cada vez.
    seen: new Set(),
    // Instante en que el backend confirmo el ultimo mensaje del usuario. Mientras dure la
    // ventana se muestra el indicador de "escribiendo"; lo apaga la respuesta o el vencimiento.
    typingSince: null,
    typingTimer: null,
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
      // Llego respuesta (bot, asesor o nota de sistema): se acabo la espera.
      if (message.sender_type !== "USER") state.typingSince = null;
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
      // El mensaje quedo durable (202): a partir de aqui se espera respuesta.
      state.typingSince = Date.now();
    } catch (error) {
      draft.status = "failed";
      draft.error = error.message;
      draft.rateLimited = error.status === 429;
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

  function render() {
    if (!root) return;
    updateLauncher();
    panelEl.classList.toggle("is-open", state.open);
    panelEl.setAttribute("aria-hidden", state.open ? "false" : "true");
    if (!state.open) return;
    const view =
      state.view === "messages" ? renderMessages() : state.view === "help" ? renderHelp() : renderHome();
    // La pantalla entra animada SOLO al cambiar de vista (o al abrir el panel). Si se animara
    // en cada render, la pantalla entera parpadearia cada vez que llega un mensaje.
    const viewKey = state.view + (state.helpArticle ? ":" + (state.helpArticle.id || "") : "");
    if (viewKey !== lastViewKey) {
      view.classList.add("is-entering");
      lastViewKey = viewKey;
    }
    const previousScroll = panelEl.querySelector(".thread");
    const wasAtBottom =
      previousScroll && previousScroll.scrollHeight - previousScroll.scrollTop - previousScroll.clientHeight < 40;
    // El re-render reemplaza el compositor: sin rescatar el borrador, un mensaje del bot que
    // llega mientras el usuario escribe le borraria lo tecleado (RF-037 protege el envio, no
    // el texto sin enviar).
    const previousComposer = panelEl.querySelector("textarea");
    const draft = previousComposer ? previousComposer.value : "";
    const caret = previousComposer ? previousComposer.selectionStart : 0;

    panelEl.replaceChildren(view);

    const thread = panelEl.querySelector(".thread");
    if (thread && (wasAtBottom || previousScroll === null)) thread.scrollTop = thread.scrollHeight;
    const composer = panelEl.querySelector("textarea");
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
      composer.focus({ preventScroll: true });
    }
  }

  /** El compositor crece con el texto hasta el tope y luego hace scroll interno. */
  function autoGrow(textarea) {
    textarea.style.height = "auto";
    textarea.style.height = Math.min(textarea.scrollHeight, CONFIG.composerMaxPx) + "px";
  }

  // El boton flotante NO se recrea en cada render: si se reemplazara, la transicion de hover
  // se cortaria cada vez que llega un mensaje. Solo se actualizan icono, estado y contador.
  function updateLauncher() {
    const open = state.open;
    launcherEl.classList.toggle("is-open", open);
    launcherEl.setAttribute("aria-label", open ? TEXT.close : TEXT.open);
    launcherIconEl.replaceChildren(open ? ICON.close() : ICON.chat());

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
    for (let i = state.messages.length - 1; i >= 0; i -= 1) {
      const message = state.messages[i];
      if (message.sender_type !== "SYSTEM" && message.message_type !== "SYSTEM") continue;
      return message.content === "HANDOFF_REQUESTED" || message.content === "ADVISOR_ASSIGNED";
    }
    return false;
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
    const typing = renderTyping();
    if (typing) items.push(typing);

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
    return h(
      "div",
      { class: "row row-typing" },
      h("div", { class: "avatar avatar-sm", text: "S", "aria-hidden": "true" }),
      h(
        "div",
        { class: "bubble typing", role: "status", "aria-label": TEXT.typing },
        h("i", {}),
        h("i", {}),
        h("i", {})
      )
    );
  }

  function renderBubble(message) {
    const mine = message.sender_type === "USER";
    // El asesor firma con su nombre (metadata.sender_name, lo pone la API); si no viene, "Asesor".
    const who = message.sender_type === "ADVISOR" ? ((message.metadata && message.metadata.sender_name) || "Asesor") : TEXT.agent;
    // El propio mensaje ya se animo como borrador: se reusa su client_message_id para que la
    // version confirmada no vuelva a entrar deslizandose.
    const fresh = firstRenderOf(message.client_message_id || message.message_id || "greeting");
    return h(
      "div",
      { class: "row" + (mine ? " row-mine" : "") + (fresh ? " is-new" : "") },
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
      { class: "row row-mine" + (firstRenderOf(clientMessageId) ? " is-new" : "") },
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

  function renderSystemEvent(message) {
    const label = SYSTEM_EVENTS[message.content] || message.content || "";
    return h(
      "div",
      {
        class: "system" + (firstRenderOf(message.message_id) ? " is-new" : ""),
        title: message.created_at ? formatTime(message.created_at) : "",
      },
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
      autoGrow(textarea);
      sendMessage(value);
    };
    textarea.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        submit();
      }
    });
    textarea.addEventListener("input", () => autoGrow(textarea));
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
    // Al cerrar se olvida la vista dibujada para que al reabrir la pantalla vuelva a entrar
    // con su animacion, en lugar de aparecer de golpe.
    if (!open) lastViewKey = null;
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
    /* ── Design system Concorde/VMC ───────────────────────────────────────────────────────
       Los tokens son los mismos de frontend/src/app/globals.css (vault, orange, teal) para que
       el widget y la app del asesor se vean del mismo producto. Van como variables locales y no
       heredadas de la pagina: el widget se embebe en VMC y :host { all: initial } corta toda
       herencia a proposito, para que el CSS del anfitrion no lo deforme.
       Patrones tomados de src/concorde/: borde en gradiente (doble background-image con
       background-clip padding-box/border-box), pildoras de radio completo, sombras tintadas de
       vault y transiciones con cubic-bezier(.25,.8,.25,1). */
    :host { all: initial; }
    * { box-sizing: border-box; }
    .root {
      --vault-400: #ae8eff; --vault-500: #8460e5; --vault-600: #5a35c2;
      --vault-700: #3b1782; --vault-900: #22005c;
      --orange-400: #fbc47d; --orange-600: #ed8936; --orange-700: #d46e20;
      --teal-500: #00aeb1;
      --ink: #191c1c; --ink-soft: #55556a; --ink-faint: #7a7a8c;
      --surface: #ffffff; --surface-soft: #f7f7fb; --line: #ececf3;
      --radius-pill: 9999px;
      /* Una sola curva para todo el widget: distintas velocidades, misma personalidad. */
      --ease: cubic-bezier(.25, .8, .25, 1);
      --shadow-vault: 0 8px 16px rgba(32, 0, 104, .2);
      --shadow-card: 0 2px 10px rgba(32, 0, 104, .08);
      font-family: "Plus Jakarta Sans", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      font-size: 14px; line-height: 1.45; color: var(--ink);
    }
    button { font: inherit; color: inherit; background: none; border: 0; cursor: pointer; padding: 0; }
    :focus-visible { outline: 2px solid var(--vault-500); outline-offset: 2px; }

    /* ── Boton flotante ──────────────────────────────────────────────────────────────────
       Mismo lenguaje que el boton primario de Concorde: relleno en gradiente vault, borde en
       gradiente y halo desenfocado que aparece al pasar el cursor. */
    .launcher {
      position: fixed; right: 20px; bottom: 20px; width: 60px; height: 60px;
      border-radius: var(--radius-pill); border: 2px solid transparent;
      color: #fff; display: grid; place-items: center; z-index: 2147483000;
      background-image:
        linear-gradient(150deg, var(--vault-500) 0%, var(--vault-700) 100%),
        linear-gradient(135deg, #cfbaff 0%, #ffffff 35%, var(--vault-400) 65%, #cfbaff 100%);
      background-origin: padding-box, border-box;
      background-clip: padding-box, border-box;
      box-shadow: rgba(255, 255, 255, .22) 0 1px 0 2px inset, rgba(32, 0, 104, .32) 0 8px 22px;
      transition: transform .24s var(--ease), box-shadow .24s var(--ease);
    }
    /* El halo va como box-shadow y no como pseudo-elemento desenfocado: el z-index alto que
       necesita el boton para vivir sobre la pagina de VMC crea un contexto de apilado, y ahi
       un ::after con z-index negativo se pintaria ENCIMA del relleno en vez de detras. */
    .launcher:hover {
      transform: translateY(-3px) scale(1.04);
      box-shadow:
        rgba(255, 255, 255, .22) 0 1px 0 2px inset,
        rgba(132, 96, 229, .5) 0 14px 32px,
        rgba(237, 137, 54, .35) 0 4px 14px;
    }
    .launcher:active { transform: translateY(-1px) scale(.98); }
    .launcher-icon { display: grid; place-items: center; transition: transform .3s var(--ease); }
    .launcher.is-open .launcher-icon { transform: rotate(90deg); }
    .badge {
      position: absolute; top: -2px; right: -2px; min-width: 22px; height: 22px; padding: 0 6px;
      border-radius: var(--radius-pill); border: 2px solid #fff;
      background: linear-gradient(150deg, var(--orange-600), var(--orange-700));
      color: #fff; font-size: 12px; font-weight: 700; display: grid; place-items: center;
      box-shadow: 0 2px 8px rgba(212, 110, 32, .45);
    }
    /* Sin esto el atributo hidden no gana al display del selector de clase. */
    .badge[hidden] { display: none; }
    .badge.is-bump { animation: badge-pop .42s var(--ease); }

    /* ── Panel ───────────────────────────────────────────────────────────────────────────
       No usa display:none para poder animar la salida; visibility lo saca del foco al cerrar. */
    .panel {
      position: fixed; right: 20px; bottom: 92px; width: 400px;
      height: min(704px, calc(100vh - 116px));
      background: var(--surface); border-radius: 22px; overflow: hidden; z-index: 2147483000;
      box-shadow: 0 24px 60px rgba(32, 0, 104, .26), 0 2px 8px rgba(32, 0, 104, .12);
      transform-origin: bottom right;
      opacity: 0; visibility: hidden; pointer-events: none;
      transform: translateY(14px) scale(.96);
      transition: opacity .18s var(--ease), transform .26s var(--ease), visibility 0s .26s;
    }
    .panel.is-open {
      opacity: 1; visibility: visible; pointer-events: auto; transform: none;
      transition: opacity .2s var(--ease), transform .3s var(--ease), visibility 0s;
    }
    @media (max-width: 480px) {
      .panel { right: 0; bottom: 0; width: 100vw; height: 100vh; border-radius: 0; transform-origin: bottom center; }
      .launcher { right: 16px; bottom: 16px; }
    }

    .screen { display: flex; flex-direction: column; height: 100%; background: var(--surface); }
    .screen.is-entering { animation: screen-in .3s var(--ease); }

    /* ── Inicio ──────────────────────────────────────────────────────────────────────────
       La cabecera lleva el gradiente vault y las tarjetas se montan sobre ella (margin-top
       negativo): da profundidad sin sombras pesadas. */
    .home { background: var(--surface-soft); }
    .home-header {
      position: relative; overflow: hidden; padding: 22px 22px 34px; color: #fff;
      border-radius: 0 0 24px 24px;
      background-image: linear-gradient(150deg, var(--vault-500) 0%, var(--vault-700) 58%, var(--vault-900) 100%);
    }
    .home-header::after {
      content: ""; position: absolute; inset: -60% -10% auto -10%; height: 220px;
      background: radial-gradient(55% 60% at 28% 0%, rgba(255, 255, 255, .26), transparent 72%);
      pointer-events: none;
    }
    .home-top { position: relative; display: flex; align-items: center; justify-content: space-between; }
    .brand { display: flex; flex-direction: column; line-height: 1.2; }
    .brand strong { font-size: 18px; letter-spacing: .01em; }
    .brand small { font-size: 10px; opacity: .82; }
    .home-header h1 { position: relative; margin: 26px 0 0; font-size: 25px; font-weight: 700; line-height: 1.22; }
    .home-body { flex: 1; overflow-y: auto; padding: 0 16px 16px; margin-top: -18px; display: flex; flex-direction: column; gap: 12px; }
    .card {
      position: relative; background: var(--surface); border-radius: 18px; padding: 15px 17px;
      text-align: left; width: 100%; border: 1px solid var(--line);
      box-shadow: var(--shadow-card);
      transition: transform .22s var(--ease), box-shadow .22s var(--ease), border-color .22s var(--ease);
    }
    button.card:hover { transform: translateY(-2px); box-shadow: var(--shadow-vault); border-color: rgba(132, 96, 229, .35); }
    button.card:active { transform: translateY(0) scale(.995); }
    .card-cta { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
    .card-cta strong { display: block; font-size: 15px; }
    .card-cta small, .search { color: var(--ink-soft); }
    /* Igual que el boton primario de Concorde: naranja que vira a vault, con brillo al pasar. */
    .cta-icon {
      position: relative; overflow: hidden; width: 38px; height: 38px; flex: none;
      border-radius: var(--radius-pill); color: #fff; display: grid; place-items: center;
      transform: rotate(90deg);
      background-image: linear-gradient(160deg, var(--orange-600) 0%, var(--orange-600) 40%, var(--vault-500) 100%);
      box-shadow: rgba(255, 255, 255, .28) 0 1px 0 1px inset, rgba(237, 137, 54, .3) 0 2px 8px;
      transition: box-shadow .25s var(--ease);
    }
    .cta-icon::before {
      content: ""; position: absolute; inset: 0; border-radius: inherit;
      background-image: linear-gradient(220deg, var(--orange-400) 0%, var(--vault-400) 100%);
      opacity: 0; transition: opacity .3s var(--ease);
    }
    .cta-icon svg { position: relative; z-index: 1; }
    button.card:hover .cta-icon::before { opacity: 1; }
    button.card:hover .cta-icon { box-shadow: rgba(255,255,255,.28) 0 1px 0 1px inset, rgba(132, 96, 229, .4) 0 6px 16px; }
    .search { display: flex; align-items: center; justify-content: space-between; width: 100%; padding: 6px 0; font-weight: 600; color: var(--ink); }
    .search svg { color: var(--vault-500); transition: transform .2s var(--ease); }
    .search:hover svg { transform: scale(1.12); }
    .list { list-style: none; margin: 0; padding: 0; }
    .list li { border-top: 1px solid var(--line); }
    .list li > button {
      display: flex; align-items: center; justify-content: space-between; width: 100%;
      padding: 12px 6px 12px 0; text-align: left; gap: 12px; border-radius: 10px;
      transition: background-color .18s var(--ease), padding-left .18s var(--ease);
    }
    .list li > button:hover { background: rgba(132, 96, 229, .07); padding-left: 8px; }
    .list li > button small { display: block; color: var(--ink-faint); font-size: 12px; }
    .list li > button svg { color: var(--vault-500); flex: none; transition: transform .2s var(--ease); }
    .list li > button:hover svg { transform: translateX(3px); }
    .list-nested { margin-left: 14px; }
    .muted { color: var(--ink-faint); margin: 8px 0 0; font-size: 13px; }
    .hint {
      font-size: 12px; color: var(--vault-700); background: rgba(132, 96, 229, .08);
      border: 1px solid rgba(132, 96, 229, .22); border-radius: 14px; padding: 11px 13px; margin: 0;
    }

    .banner { padding: 10px 16px; font-size: 13px; animation: fade-in .24s var(--ease); }
    .banner p { margin: 0 0 6px; }
    .banner-error { background: #fff1f0; color: #8a1c12; }
    .banner-warn { background: #fff8e6; color: #7a5200; }
    .link { color: var(--vault-600); text-decoration: underline; font-weight: 600; transition: color .18s var(--ease); }
    .link:hover { color: var(--vault-500); }

    /* ── Barras superiores ───────────────────────────────────────────────────────────────
       Cabecera clara con una linea de acento vault: separa sin el peso de un borde gris. */
    .bar {
      display: flex; align-items: center; gap: 10px; padding: 12px; background: var(--surface);
      border-bottom: 1px solid var(--line);
      box-shadow: 0 1px 0 rgba(132, 96, 229, .12);
    }
    .bar-plain { justify-content: space-between; padding: 14px 16px; }
    .bar-title { flex: 1; display: flex; flex-direction: column; line-height: 1.2; min-width: 0; }
    .bar-title strong { font-size: 15px; }
    .bar-title small { color: var(--ink-soft); font-size: 12px; }
    .icon-btn {
      width: 36px; height: 36px; border-radius: var(--radius-pill); display: grid; place-items: center;
      color: var(--ink-soft); flex: none;
      transition: background-color .18s var(--ease), color .18s var(--ease), transform .18s var(--ease);
    }
    .icon-btn:hover { background: rgba(132, 96, 229, .1); color: var(--vault-600); }
    .icon-btn:active { transform: scale(.92); }
    .avatar {
      width: 36px; height: 36px; border-radius: var(--radius-pill); color: #fff; font-weight: 700;
      display: grid; place-items: center; flex: none;
      background-image: linear-gradient(150deg, var(--vault-500), var(--vault-700));
      box-shadow: 0 2px 8px rgba(32, 0, 104, .22);
    }
    .avatar-lg { width: 44px; height: 44px; border: 2px solid rgba(255, 255, 255, .55); }
    .avatar-sm { width: 26px; height: 26px; font-size: 12px; align-self: flex-end; box-shadow: none; }

    /* ── Hilo ────────────────────────────────────────────────────────────────────────────*/
    .thread { flex: 1; overflow-y: auto; padding: 16px 14px; display: flex; flex-direction: column; gap: 10px; background: var(--surface); scroll-behavior: smooth; }
    .thread::-webkit-scrollbar, .home-body::-webkit-scrollbar, .help-body::-webkit-scrollbar, .article::-webkit-scrollbar { width: 8px; }
    .thread::-webkit-scrollbar-thumb, .home-body::-webkit-scrollbar-thumb, .help-body::-webkit-scrollbar-thumb, .article::-webkit-scrollbar-thumb { background: rgba(132, 96, 229, .22); border-radius: var(--radius-pill); }
    .thread::-webkit-scrollbar-thumb:hover, .home-body::-webkit-scrollbar-thumb:hover { background: rgba(132, 96, 229, .38); }
    .ready { text-align: center; color: var(--ink-faint); font-size: 13px; margin-bottom: 4px; }
    .day { align-self: center; font-size: 11px; color: var(--ink-faint); text-transform: uppercase; letter-spacing: .04em; margin: 6px 0 2px; }
    .row { display: flex; gap: 8px; max-width: 85%; }
    .row-mine { align-self: flex-end; flex-direction: row-reverse; }
    /* Solo las burbujas nuevas entran animadas (lo decide firstRenderOf en el JS). */
    .row.is-new { animation: bubble-in .32s var(--ease) both; }
    .row-mine.is-new { animation-name: bubble-in-mine; }
    .row-typing { animation: fade-in .2s var(--ease) both; }
    .bubble-wrap { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
    .row-mine .bubble-wrap { align-items: flex-end; }
    .bubble {
      background: var(--surface-soft); color: var(--ink); border: 1px solid var(--line);
      border-radius: 18px 18px 18px 6px; padding: 10px 14px;
      white-space: pre-wrap; word-break: break-word;
      box-shadow: 0 1px 2px rgba(32, 0, 104, .05);
    }
    .bubble-mine {
      color: #fff; border: 0; border-radius: 18px 18px 6px 18px;
      background-image: linear-gradient(150deg, var(--vault-500) 0%, var(--vault-700) 100%);
      box-shadow: 0 4px 12px rgba(32, 0, 104, .22);
    }
    .bubble a { color: inherit; text-decoration: underline; text-underline-offset: 2px; }
    .bubble-pending { opacity: .62; }
    .bubble-failed { background-image: linear-gradient(150deg, #d14343, #b3261e); }
    .typing { display: inline-flex; align-items: center; gap: 5px; padding: 13px 16px; }
    .typing i { width: 6px; height: 6px; border-radius: 50%; background: var(--vault-500); display: block; animation: typing-dot 1.25s infinite var(--ease); }
    .typing i:nth-child(2) { animation-delay: .16s; }
    .typing i:nth-child(3) { animation-delay: .32s; }
    .meta { font-size: 11px; color: var(--ink-faint); }
    .meta-error { color: #b3261e; }
    .system { align-self: center; display: flex; align-items: center; gap: 10px; color: var(--ink-faint); font-size: 12px; width: 100%; margin: 6px 0; }
    .system.is-new { animation: fade-in .3s var(--ease) both; }
    .system::before, .system::after { content: ""; flex: 1; height: 1px; background: linear-gradient(90deg, transparent, rgba(132, 96, 229, .3), transparent); }

    /* ── Compositor ──────────────────────────────────────────────────────────────────────
       Borde en gradiente igual que el Input de Concorde: vault en reposo, naranja a vault con
       foco. El textarea crece con el texto (autoGrow) hasta composerMaxPx. */
    .composer { display: flex; align-items: flex-end; gap: 8px; padding: 10px 12px; border-top: 1px solid var(--line); background: var(--surface); }
    .composer textarea {
      flex: 1; resize: none; padding: 11px 15px; font: inherit; color: var(--ink);
      border: 1.5px solid transparent; border-radius: 18px; outline: none;
      max-height: 132px; overflow-y: auto;
      background-image: linear-gradient(#fff, #fff), linear-gradient(338deg, var(--vault-500) 0%, #fff8f1 100%);
      background-origin: border-box; background-clip: padding-box, border-box;
      transition: box-shadow .22s var(--ease), background-image .22s var(--ease);
    }
    .composer textarea::placeholder { color: #6b7280; }
    .composer textarea:focus {
      background-image: linear-gradient(#fff, #fff), linear-gradient(148deg, var(--orange-600) 0%, var(--vault-500) 100%);
      box-shadow: rgba(237, 137, 54, .18) 0 2px 10px;
    }
    .send {
      position: relative; overflow: hidden; width: 42px; height: 42px; flex: none;
      border-radius: var(--radius-pill); color: #fff; display: grid; place-items: center;
      background-image: linear-gradient(160deg, var(--orange-600) 0%, var(--orange-600) 40%, var(--vault-500) 100%);
      box-shadow: rgba(255, 255, 255, .28) 0 1px 0 1px inset, rgba(237, 137, 54, .3) 0 2px 8px;
      transition: transform .2s var(--ease), box-shadow .25s var(--ease);
    }
    .send::before {
      content: ""; position: absolute; inset: 0; border-radius: inherit;
      background-image: linear-gradient(220deg, var(--orange-400) 0%, var(--vault-400) 100%);
      opacity: 0; transition: opacity .3s var(--ease);
    }
    .send svg { position: relative; z-index: 1; transition: transform .2s var(--ease); }
    .send:hover { transform: translateY(-2px); box-shadow: rgba(255,255,255,.28) 0 1px 0 1px inset, rgba(132, 96, 229, .4) 0 8px 20px; }
    .send:hover::before { opacity: 1; }
    .send:hover svg { transform: translateY(-1px); }
    .send:active { transform: translateY(0) scale(.94); }

    /* ── Navegacion inferior ─────────────────────────────────────────────────────────────
       La pestaña activa se marca con una barra vault que se dibuja de dentro hacia fuera. */
    .nav { display: flex; border-top: 1px solid var(--line); background: var(--surface); }
    .nav-item {
      position: relative; flex: 1; display: flex; flex-direction: column; align-items: center; gap: 3px;
      padding: 11px 0 13px; font-size: 12px; color: var(--ink-soft);
      transition: color .2s var(--ease);
    }
    /* -1px para que la barra tape la linea del borde y no quede flotando sobre ella. */
    .nav-item::after {
      content: ""; position: absolute; top: -1px; left: 50%; width: 34px; height: 3px;
      border-radius: 0 0 3px 3px; background: linear-gradient(90deg, var(--vault-500), var(--vault-700));
      transform: translate(-50%, -3px) scaleX(0); transform-origin: center;
      transition: transform .28s var(--ease);
    }
    .nav-item:hover { color: var(--vault-600); }
    .nav-item svg { transition: transform .2s var(--ease); }
    .nav-item:hover svg { transform: translateY(-1px); }
    .nav-item.is-active { color: var(--vault-600); font-weight: 600; }
    .nav-item.is-active::after { transform: translate(-50%, 0) scaleX(1); }

    .help-body { flex: 1; overflow-y: auto; padding: 0 16px 16px; }
    .help-intro { display: flex; flex-direction: column; padding: 14px 0; }
    .help-intro small { color: var(--ink-soft); }
    .article { flex: 1; overflow-y: auto; padding: 16px; }
    .article p { margin: 0 0 12px; }

    /* ── Animaciones ─────────────────────────────────────────────────────────────────────*/
    @keyframes screen-in { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }
    @keyframes fade-in { from { opacity: 0; } to { opacity: 1; } }
    @keyframes bubble-in { from { opacity: 0; transform: translateY(10px) translateX(-6px) scale(.97); } to { opacity: 1; transform: none; } }
    @keyframes bubble-in-mine { from { opacity: 0; transform: translateY(10px) translateX(6px) scale(.97); } to { opacity: 1; transform: none; } }
    @keyframes typing-dot { 0%, 60%, 100% { transform: translateY(0); opacity: .4; } 30% { transform: translateY(-4px); opacity: 1; } }
    @keyframes badge-pop { 0% { transform: scale(.4); opacity: 0; } 60% { transform: scale(1.18); opacity: 1; } 100% { transform: scale(1); } }

    /* Accesibilidad: quien pide menos movimiento recibe los mismos estados, sin recorrido.
       Misma regla que traen los componentes de Concorde. */
    @media (prefers-reduced-motion: reduce) {
      .root *, .root *::before, .root *::after {
        animation-duration: .001ms !important; animation-iteration-count: 1 !important;
        transition-duration: .001ms !important;
      }
      .thread { scroll-behavior: auto; }
    }
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
    launcherIconEl = h("span", { class: "launcher-icon" });
    launcherBadgeEl = h("span", { class: "badge", hidden: true });
    launcherEl = h(
      "button",
      {
        class: "launcher",
        type: "button",
        "aria-label": TEXT.open,
        onclick: () => setOpen(!state.open),
      },
      launcherIconEl,
      launcherBadgeEl
    );
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
