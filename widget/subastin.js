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
    // Cadencias del sondeo (TD-001, revisado 2026-09-02): se sondea SOLO cuando algo puede
    // llegar. Esperando al bot: rapido; caso con asesor: medio; hilo del bot en reposo: lento
    // (cubre la intervencion proactiva de D-022); panel cerrado: la lista de casos o nada.
    pollWaitingMs: 2000,
    pollAdvisorMs: 5000,
    pollOpenMs: 15000,
    pollClosedMs: 60000,
    pollAnonPendingClosedMs: 30000,
    listEveryMs: 30000,
    // Backoff exponencial con jitter ante error de red o 5xx: una API caida no recibe un
    // martillo de 2,5 s por pestaña, y al volver no vuelven todas sincronizadas.
    backoffBaseMs: 5000,
    backoffMaxMs: 60000,
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
    // Abre la conversacion UNA vez (ver renderMessages): es el inicio del hilo, no un mensaje
    // que llega. El salto de linea separa el "hola" de la pregunta, como dos frases reales.
    greetingAuth: (name) =>
      `¡Hola! 👋 ${name}.\n\nAhora estás hablando con Subastín. ¿Cómo puedo ayudarte?`,
    greetingAnon:
      "¡Hola! 👋 Cazador de Ofertas.\n\nAhora estás hablando con Subastín. ¿Cómo puedo ayudarte?",
    homeTitleAuth: (name) => `¡Bienvenido al Nuevo VMC ${name}! ¿Cómo podemos ayudarte?`,
    homeTitleAnon: "¡Bienvenido al Nuevo VMC! ¿Cómo podemos ayudarte?",
    sendUs: "Envíanos un mensaje",
    sendUsSub: "Solemos responder en unos minutos",
    searchHelp: "Buscar ayuda",
    navHome: "Inicio",
    navMessages: "Mensajes",
    navHelp: "Ayuda",
    agentStatus: "En línea",
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
    minimize: "Minimizar el chat",
    attach: "Adjuntar archivo",
    emoji: "Insertar emoji",
    soon: "Muy pronto",
    // D-029: casos, lista de conversaciones y formulario de asesor.
    inboxTitle: "Mensajes",
    threadName: "Subastín",
    statusPending: "Esperando asesor",
    statusAttending: "Un asesor te atiende",
    statusClosed: "Cerrada",
    waitingBanner: "Un asesor te responderá aquí. Puedes seguir escribiendo detalles mientras tanto.",
    closedCase: "Este caso está cerrado.",
    closedAnon: "Esta conversación se cerró.",
    newConversation: "Nueva conversación",
    backToBot: "Volver a Subastín",
    olderMessages: "Ver mensajes anteriores",
    formSending: "Enviando…",
    formFailed: "No se pudo enviar. Inténtalo de nuevo.",
    formRequired: "Completa este campo",
    noCases: "Cuando pidas un asesor, tu caso aparecerá aquí.",
    offlineStatus: "Sin conexión",
    caseOpenedFrom: (title) => (title ? `Abriste el caso «${title}»` : "Abriste un caso para un asesor"),
    caseOpenedHere: "Caso abierto desde tu chat con Subastín",
    openCase: "Ver caso",
  };

  // Eventos de auditoria que llegan como mensajes SYSTEM (conversations/models.py SystemEvent)
  // y su texto en el hilo, al estilo de las notas de sistema de Intercom.
  const SYSTEM_EVENTS = {
    HANDOFF_REQUESTED: "Solicitaste hablar con un asesor",
    ADVISOR_ASSIGNED: "Un asesor se unió a la conversación",
    TICKET_OPENED: "Ticket abierto",
    TICKET_CLOSED: "El asesor cerró la atención. Subastín vuelve a responder",
    BOT_DISABLED: "Subastín dejó de responder mientras un asesor atiende tu caso",
    BOT_ENABLED: "Subastín vuelve a atenderte",
    CONVERSATION_CLOSED: "Conversación cerrada",
    CASE_OPENED: "Caso abierto",
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
    // Arranca (y re-abre) SIEMPRE en mensajes: el home queda para quien navegue a el.
    view: "messages", // home | messages | help
    // El saludo de una conversacion RECIEN abierta no aparece junto con el panel: primero
    // abre el panel (su propia transicion) y ~400 ms despues "llega" con su fade, como un
    // mensaje de verdad. Sin esa espera las dos animaciones se pisan y parece parte del
    // panel. Solo aplica al hilo vacio: con historial el saludo ya esta arriba y no "llega".
    greetingVisible: false,
    greetingTimer: null,
    // Tope de caracteres del compositor. Se reemplaza con el que informa la sesion; este valor
    // solo cubre el instante previo a la primera respuesta de /chat/sessions.
    maxChars: 500,
    // Scroll del hilo: si el usuario esta abajo, cada mensaje nuevo lo sigue; si subio a leer,
    // se respeta su posicion y se le avisa con una pildora.
    stickToBottom: true,
    unseenBelow: 0,
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
    // D-029: hilo del bot + casos. `activeId` es la conversacion abierta en la vista de
    // mensajes; `conversation` su estado vigente (llega en cada sondeo) y `threads` guarda
    // los mensajes ya cargados de las demas para no volver a pedirlos al cambiar.
    conversations: [],
    activeId: null,
    conversation: null,
    threads: new Map(),
    firstKey: null,
    hasMore: false,
    loadingOlder: false,
    pollAgain: false,
    // Fallos seguidos del sondeo (backoff) y ultima carga de la lista.
    failures: 0,
    lastListAt: 0,
    // Ultimo `last_message_at` visto por conversacion: con el panel cerrado, un caso que
    // avanzo desde entonces suma al contador del boton flotante.
    seenAt: {},
    // Formulario de asesor en curso: borrador (sobrevive al re-render), error y envio.
    formDraft: {},
    formError: null,
    formBusy: false,
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

  // Trazo del wordmark de VMC (fuente: widget/logo-voyager.svg). Si la marca cambia, se edita
  // el SVG y se vuelve a copiar de ahi. La palabra SUBASTAS no viaja como contornos: son
  // 6,5 KB de trazos para un texto de 5 px, asi que se dibuja con <text> (ver brandLogo).
  const LOGO_WORDMARK =
    "M11.9956 31.3252L0 0.74584H12.9279L19.9512 26.7881H15.5383L22.4995 0.74584H35.3652L23.3696 31.3252H11.9956ZM35.6138 31.3252V0.74584H47.7959V31.3252H35.6138ZM54.4463 31.3252V13.798C54.4463 12.7621 54.1355 11.9438 53.514 11.343C52.8924 10.7422 52.1052 10.4417 51.1521 10.4417C50.4892 10.4417 49.8987 10.5764 49.3808 10.8457C48.8628 11.1151 48.4692 11.4984 48.1999 11.9956C47.9305 12.4928 47.7959 13.0936 47.7959 13.798L43.0722 12.0577C43.0722 9.5716 43.6212 7.43767 44.7193 5.65595C45.8173 3.87422 47.2986 2.50685 49.1632 1.55383C51.0278 0.600815 53.141 0.124307 55.5029 0.124307C57.5746 0.124307 59.4496 0.621532 61.1277 1.61598C62.8059 2.61044 64.1422 3.98817 65.1366 5.74918C66.1311 7.51019 66.6283 9.59232 66.6283 11.9956V31.3252H54.4463ZM73.2787 31.3252V13.798C73.2787 12.7621 72.9679 11.9438 72.3464 11.343C71.7249 10.7422 70.9376 10.4417 69.9846 10.4417C69.3216 10.4417 68.7312 10.5764 68.2132 10.8457C67.6953 11.1151 67.3016 11.4984 67.0323 11.9956C66.763 12.4928 66.6283 13.0936 66.6283 13.798L59.4807 13.8602C59.4807 11.0011 60.0504 8.54607 61.1899 6.49502C62.3294 4.44396 63.9143 2.86941 65.9446 1.77137C67.975 0.673327 70.2953 0.124307 72.9058 0.124307C75.3505 0.124307 77.5155 0.642251 79.4008 1.67814C81.2861 2.71403 82.7674 4.2057 83.8448 6.15317C84.9221 8.10064 85.4607 10.4417 85.4607 13.1765V31.3252H73.2787ZM103.609 32.0711C100.295 32.0711 97.3113 31.3874 94.6594 30.02C92.0075 28.6527 89.9151 26.757 88.3819 24.333C86.8488 21.909 86.0823 19.1639 86.0823 16.0977C86.0823 12.99 86.8592 10.2242 88.413 7.80023C89.9669 5.37626 92.0801 3.47022 94.7527 2.08213C97.4252 0.694045 100.44 0 103.796 0C106.199 0 108.364 0.37292 110.291 1.11876C112.218 1.8646 114.01 3.00407 115.667 4.53719L108.022 12.182C107.484 11.6848 106.883 11.3119 106.22 11.0633C105.557 10.8147 104.749 10.6904 103.796 10.6904C102.802 10.6904 101.9 10.9079 101.092 11.343C100.284 11.778 99.6317 12.3892 99.1345 13.1765C98.6372 13.9638 98.3886 14.8961 98.3886 15.9734C98.3886 17.0507 98.6372 17.9934 99.1345 18.8014C99.6317 19.6094 100.295 20.2412 101.123 20.697C101.952 21.1528 102.843 21.3807 103.796 21.3807C104.873 21.3807 105.764 21.215 106.469 20.8835C107.173 20.552 107.794 20.0962 108.333 19.5161L115.978 27.161C114.196 28.8184 112.332 30.0511 110.384 30.8591C108.437 31.6671 106.178 32.0711 103.609 32.0711Z";

  const ICON = {
    chat: () => svg(["M4 5h16v11H8l-4 4V5z"], 26),
    close: () => svg(["M6 6l12 12M18 6L6 18"], 22),
    home: () => svg(["M3 11l9-8 9 8v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1v-9z"]),
    messages: () => svg(["M4 5h16v11H8l-4 4V5z", "M8 9h8M8 12h5"]),
    help: () => svg(["M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z", "M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.7.4-1 .9-1 1.7", "M12 17h.01"]),
    send: () => svg(["M12 19V5", "M6 11l6-6 6 6"], 20),
    back: () => svg(["M15 18l-6-6 6-6"], 22),
    chevron: () => svg(["M9 6l6 6-6 6"], 18),
    // El launcher abierto "minimiza" (chevron hacia abajo), no "cierra" con una X: el patron
    // de Intercom que la pagina anfitriona ya le enseño a los usuarios de VMC.
    minimize: () => svg(["M6 9.5l6 6 6-6"], 24),
    clip: () => svg(["M21 11.6l-8.9 8.9a5.6 5.6 0 0 1-7.9-7.9l8.9-8.9a3.7 3.7 0 0 1 5.3 5.3l-8.9 8.9a1.9 1.9 0 0 1-2.6-2.6l8.2-8.2"], 19),
    smile: () => svg(["M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z", "M8.6 13.8s1.2 1.9 3.4 1.9 3.4-1.9 3.4-1.9", "M9.2 9.6h.01M14.8 9.6h.01"], 19),
    search: () => svg(["M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16z", "M21 21l-4.3-4.3"], 18),
  };

  /** Logotipo de VMC (fuente: widget/logo-voyager.svg) como nodos SVG. Va inline y no como
   *  <img src>: el widget se embebe en la pagina de VMC sin build ni assets propios, asi que un
   *  archivo suelto obligaria a publicarlo y versionarlo aparte. El id del gradiente lleva
   *  prefijo porque el shadow DOM comparte espacio de ids con el resto de defs del widget. */
  function brandLogo() {
    const ns = "http://www.w3.org/2000/svg";
    const make = (tag, attrs) => {
      const node = document.createElementNS(ns, tag);
      for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
      return node;
    };
    const el = make("svg", {
      viewBox: "0 0 119 45", width: "124", height: "47", fill: "none",
      role: "img", "aria-label": TEXT.brand,
    });
    el.appendChild(make("path", { d: LOGO_WORDMARK, fill: "currentColor" }));
    const defs = document.createElementNS(ns, "defs");
    const gradient = make("linearGradient", {
      id: "subastin-logo-underline", x1: "2.52637", y1: "40.5081", x2: "118.512", y2: "40.5081",
      gradientUnits: "userSpaceOnUse",
    });
    for (const [offset, color, opacity] of [
      ["0", "#ED8936", "0"], ["0.12", "#ED8936", "0.85"], ["0.35", "#AE8EFF", "0.85"],
      ["0.55", "#8460E5", "0.85"], ["0.75", "#5A35C2", "0.85"], ["1", "#5A35C2", "0"],
    ]) {
      gradient.appendChild(make("stop", { offset, "stop-color": color, "stop-opacity": opacity }));
    }
    defs.appendChild(gradient);
    el.appendChild(defs);
    el.appendChild(make("rect", {
      x: "2.52637", y: "36.9893", width: "115.986", height: "7.03765",
      fill: "url(#subastin-logo-underline)",
    }));
    const palabra = make("text", {
      x: "62.9", y: "42", "text-anchor": "middle", fill: "#2E0F70",
      "font-size": "4.5", "font-weight": "600", "letter-spacing": "3.18",
      "font-family": "inherit",
    });
    palabra.textContent = "SUBASTAS";
    el.appendChild(palabra);
    return el;
  }

  /** Avatar de Subastin: un bot dibujado en SVG, en vez de la inicial "S". Los ojos parpadean
   *  con CSS (clase .bot-eye) y el conjunto flota apenas al pasar el cursor.
   *  NOTA: no usa widget/Anima-Bot.json (Lottie) a proposito — reproducirlo exige cargar
   *  lottie-web (~140 KB gzip) en TODA pagina de VMC que embeba el widget, demasiado peso para
   *  un avatar. El JSON queda en el repo por si se decide asumir ese costo. */
  function botAvatar(className, animated) {
    const ns = "http://www.w3.org/2000/svg";
    const el = document.createElementNS(ns, "svg");
    el.setAttribute("viewBox", "0 0 32 32");
    el.setAttribute("fill", "none");
    el.setAttribute("aria-hidden", "true");
    el.setAttribute("class", "bot-icon");
    const add = (tag, attrs) => {
      const node = document.createElementNS(ns, tag);
      for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
      el.appendChild(node);
    };
    const trazo = { stroke: "currentColor", "stroke-width": "1.9", "stroke-linecap": "round" };
    add("path", Object.assign({ d: "M16 5.4v2.4" }, trazo));              // antena
    add("circle", { cx: "16", cy: "3.7", r: "1.7", fill: "currentColor" });
    add("rect", Object.assign({ x: "5.9", y: "7.8", width: "20.2", height: "15.2", rx: "6.3",
                                fill: "none" }, trazo));                  // cabeza
    add("path", Object.assign({ d: "M3.1 13.6v3.6M28.9 13.6v3.6" }, trazo)); // orejas
    add("ellipse", { cx: "12.1", cy: "14.7", rx: "1.7", ry: "2.05", fill: "currentColor", class: "bot-eye" });
    add("ellipse", { cx: "19.9", cy: "14.7", rx: "1.7", ry: "2.05", fill: "currentColor", class: "bot-eye" });
    add("path", Object.assign({ d: "M12.7 18.9c1 .85 2.1 1.28 3.3 1.28s2.3-.43 3.3-1.28" },
                              trazo, { "stroke-width": "1.7" }));         // sonrisa
    const wrap = h("div", { class: className, "aria-hidden": "true" });
    if (animated) wrap.setAttribute("data-bot-animated", "");
    wrap.appendChild(el);
    return wrap;
  }


  // ── Avatar animado (Anima-Bot) ──────────────────────────────────────────────────────────
  // Decision de producto (Aaron, 2026-08-31): el avatar del bot es la animacion Anima-Bot
  // (Lottie, widget/Anima-Bot.json embebido abajo sin nombres de capa). lottie_light
  // (~45 KB gzip, cdnjs) se carga UNA sola vez y recien cuando alguien abre el panel: la
  // pagina de VMC no paga nada hasta que se usa el chat. Si el CDN falla o esta bloqueado,
  // queda el bot SVG estatico — el chat nunca depende de esto. Solo se animan los avatares
  // grandes (cabecera y barra del hilo); los de burbuja quedan estaticos a proposito: a
  // 26 px la animacion es ruido y multiplicaria instancias.
  const LOTTIE_SRC = "https://cdnjs.cloudflare.com/ajax/libs/bodymovin/5.12.2/lottie_light.min.js";
  let lottieState = "idle"; // idle | loading | ready | failed
  const lottieMounts = []; // { el, anim } vivos, para destruir los que salgan del DOM

  function ensureLottie() {
    if (lottieState !== "idle") return;
    lottieState = "loading";
    const script = document.createElement("script");
    script.src = LOTTIE_SRC;
    script.async = true;
    script.onload = () => {
      lottieState = "ready";
      render();
    };
    script.onerror = () => {
      lottieState = "failed";
    };
    document.head.appendChild(script);
  }

  /** Monta el Lottie en los avatares marcados y desmonta los que ya no estan en pantalla
   *  (cada render reconstruye la vista, asi que hay que limpiar instancias huerfanas). */
  function mountAnimatedAvatars() {
    for (let i = lottieMounts.length - 1; i >= 0; i--) {
      if (!lottieMounts[i].el.isConnected) {
        lottieMounts[i].anim.destroy();
        lottieMounts.splice(i, 1);
      }
    }
    if (lottieState !== "ready" || !window.lottie || !root) return;
    for (const el of root.querySelectorAll("[data-bot-animated]:not(.is-lottie)")) {
      el.classList.add("is-lottie");
      el.textContent = "";
      const anim = window.lottie.loadAnimation({
        container: el,
        renderer: "svg",
        loop: true,
        autoplay: true,
        // Copia fresca por montaje: lottie muta el objeto que recibe.
        animationData: JSON.parse(BOT_ANIMATION_JSON),
      });
      lottieMounts.push({ el, anim });
    }
  }

  const BOT_ANIMATION_JSON = "{\"ddd\":0,\"h\":1080,\"w\":1080,\"layers\":[{\"ty\":0,\"sr\":0.9,\"st\":0,\"op\":81,\"ip\":0,\"hd\":false,\"ddd\":0,\"bm\":0,\"hasMask\":false,\"ao\":0,\"ks\":{\"a\":{\"a\":0,\"k\":[540,540,0],\"ix\":1},\"s\":{\"a\":0,\"k\":[100,100,100],\"ix\":6},\"sk\":{\"a\":0,\"k\":0},\"p\":{\"a\":0,\"k\":[568,540,0],\"ix\":2},\"r\":{\"a\":0,\"k\":0,\"ix\":10},\"sa\":{\"a\":0,\"k\":0},\"o\":{\"a\":0,\"k\":100,\"ix\":11}},\"ef\":[],\"w\":1080,\"h\":1080,\"refId\":\"comp_0\",\"ind\":1}],\"v\":\"5.7.0\",\"fr\":30,\"op\":81,\"ip\":0,\"assets\":[{\"id\":\"comp_0\",\"layers\":[{\"ty\":4,\"sr\":1,\"st\":0,\"op\":300,\"ip\":0,\"hd\":false,\"ddd\":0,\"bm\":0,\"hasMask\":false,\"ao\":0,\"ks\":{\"a\":{\"a\":0,\"k\":[-221.715,95.051,0],\"ix\":1},\"s\":{\"a\":0,\"k\":[100,100,100],\"ix\":6},\"sk\":{\"a\":0,\"k\":0},\"p\":{\"a\":1,\"k\":[{\"o\":{\"x\":0.333,\"y\":0},\"i\":{\"x\":0.667,\"y\":1},\"s\":[180.285,91.051,0],\"t\":0,\"ti\":[-0.167,0.333,0],\"to\":[-0.5,2.333,0]},{\"o\":{\"x\":0.333,\"y\":0},\"i\":{\"x\":0.667,\"y\":1},\"s\":[177.285,105.051,0],\"t\":28,\"ti\":[-0.667,4,0],\"to\":[0.167,-0.333,0]},{\"o\":{\"x\":0.333,\"y\":0},\"i\":{\"x\":0.667,\"y\":1},\"s\":[181.285,89.051,0],\"t\":49,\"ti\":[0.167,-0.333,0],\"to\":[0.667,-4,0]},{\"o\":{\"x\":0.333,\"y\":0},\"i\":{\"x\":0.667,\"y\":1},\"s\":[181.285,81.051,0],\"t\":67,\"ti\":[0.167,-1.667,0],\"to\":[-0.167,0.333,0]},{\"s\":[180.285,91.051,0],\"t\":89}],\"ix\":2},\"r\":{\"a\":1,\"k\":[{\"o\":{\"x\":0.333,\"y\":0},\"i\":{\"x\":0.667,\"y\":1},\"s\":[190],\"t\":7},{\"o\":{\"x\":0.333,\"y\":0},\"i\":{\"x\":0.667,\"y\":1.019},\"s\":[191],\"t\":28},{\"o\":{\"x\":0.333,\"y\":0.034},\"i\":{\"x\":0.667,\"y\":1},\"s\":[198.741],\"t\":45},{\"s\":[190],\"t\":79}],\"ix\":10},\"sa\":{\"a\":0,\"k\":0},\"o\":{\"a\":0,\"k\":100,\"ix\":11}},\"ef\":[],\"shapes\":[{\"ty\":\"gr\",\"bm\":0,\"hd\":false,\"ix\":1,\"cix\":2,\"np\":3,\"it\":[{\"ty\":\"sh\",\"bm\":0,\"hd\":false,\"ix\":1,\"d\":1,\"ks\":{\"a\":0,\"k\":{\"c\":true,\"i\":[[4.87,-6.025],[-8,-27],[-10.721,6.14],[-0.455,5.253],[-4,11],[8.822,3.516]],\"o\":[[-59,73],[4.497,15.177],[8.352,-4.783],[9,-104],[1.863,-5.123],[-10.121,-4.034]],\"v\":[[-242.5,83.5],[-273,271],[-238.265,285.283],[-229,261],[-201,97],[-210.355,75.636]]},\"ix\":2}},{\"ty\":\"st\",\"bm\":0,\"hd\":false,\"lc\":1,\"lj\":1,\"ml\":4,\"o\":{\"a\":0,\"k\":100,\"ix\":4},\"w\":{\"a\":0,\"k\":0,\"ix\":5},\"c\":{\"a\":0,\"k\":[1,1,1],\"ix\":3}},{\"ty\":\"gf\",\"bm\":0,\"hd\":false,\"e\":{\"a\":0,\"k\":[-283.121,160.699],\"ix\":6},\"g\":{\"p\":3,\"k\":{\"a\":0,\"k\":[0,0.9215686274509803,0.9568627450980393,0.9882352941176471,0.655,0.8666666666666667,0.8823529411764706,0.9019607843137255,1,0.8117647058823529,0.8117647058823529,0.8117647058823529],\"ix\":9}},\"t\":1,\"a\":{\"a\":0,\"k\":0},\"h\":{\"a\":0,\"k\":0},\"s\":{\"a\":0,\"k\":[-235.688,173.874],\"ix\":5},\"r\":1,\"o\":{\"a\":0,\"k\":100,\"ix\":10}},{\"ty\":\"tr\",\"a\":{\"a\":0,\"k\":[0,0],\"ix\":1},\"s\":{\"a\":0,\"k\":[100,100],\"ix\":3},\"sk\":{\"a\":0,\"k\":0,\"ix\":4},\"p\":{\"a\":0,\"k\":[0,0],\"ix\":2},\"r\":{\"a\":0,\"k\":0,\"ix\":6},\"sa\":{\"a\":0,\"k\":0,\"ix\":5},\"o\":{\"a\":0,\"k\":100,\"ix\":7}}]}],\"ind\":1,\"parent\":7},{\"ty\":4,\"sr\":1,\"st\":0,\"op\":300,\"ip\":0,\"hd\":false,\"ddd\":0,\"bm\":0,\"hasMask\":false,\"ao\":0,\"ks\":{\"a\":{\"a\":0,\"k\":[-223.715,93.051,0],\"ix\":1},\"s\":{\"a\":0,\"k\":[100,100,100],\"ix\":6},\"sk\":{\"a\":0,\"k\":0},\"p\":{\"a\":1,\"k\":[{\"o\":{\"x\":0.333,\"y\":0},\"i\":{\"x\":0.667,\"y\":1},\"s\":[-223.715,93.051,0],\"t\":3,\"ti\":[0,0,0],\"to\":[0,4.333,0]},{\"o\":{\"x\":0.333,\"y\":0},\"i\":{\"x\":0.667,\"y\":1},\"s\":[-223.715,119.051,0],\"t\":31,\"ti\":[0,4.333,0],\"to\":[0,0,0]},{\"o\":{\"x\":0.333,\"y\":0},\"i\":{\"x\":0.667,\"y\":1},\"s\":[-223.715,93.051,0],\"t\":52,\"ti\":[0,0,0],\"to\":[0,0,0]},{\"o\":{\"x\":0.333,\"y\":0},\"i\":{\"x\":0.667,\"y\":1},\"s\":[-223.715,76.051,0],\"t\":70,\"ti\":[0,0,0],\"to\":[0,0,0]},{\"s\":[-223.715,93.051,0],\"t\":89}],\"ix\":2},\"r\":{\"a\":1,\"k\":[{\"o\":{\"x\":0.167,\"y\":0.167},\"i\":{\"x\":0.667,\"y\":1},\"s\":[0],\"t\":3},{\"o\":{\"x\":0.296,\"y\":0},\"i\":{\"x\":0.665,\"y\":0.832},\"s\":[-11],\"t\":40},{\"o\":{\"x\":0.428,\"y\":-0.7},\"i\":{\"x\":0.811,\"y\":1.256},\"s\":[3.659],\"t\":67},{\"s\":[0],\"t\":89}],\"ix\":10},\"sa\":{\"a\":0,\"k\":0},\"o\":{\"a\":0,\"k\":100,\"ix\":11}},\"ef\":[],\"shapes\":[{\"ty\":\"gr\",\"bm\":0,\"hd\":false,\"ix\":1,\"cix\":2,\"np\":3,\"it\":[{\"ty\":\"sh\",\"bm\":0,\"hd\":false,\"ix\":1,\"d\":1,\"ks\":{\"a\":0,\"k\":{\"c\":true,\"i\":[[4.87,-6.025],[-8,-27],[-10.721,6.14],[-0.455,5.253],[-4,11],[8.822,3.516]],\"o\":[[-59,73],[4.497,15.177],[8.352,-4.783],[9,-104],[1.863,-5.123],[-10.121,-4.034]],\"v\":[[-242.5,83.5],[-273,271],[-238.265,285.283],[-229,261],[-201,97],[-210.355,75.636]]},\"ix\":2}},{\"ty\":\"st\",\"bm\":0,\"hd\":false,\"lc\":1,\"lj\":1,\"ml\":4,\"o\":{\"a\":0,\"k\":100,\"ix\":4},\"w\":{\"a\":0,\"k\":0,\"ix\":5},\"c\":{\"a\":0,\"k\":[1,1,1],\"ix\":3}},{\"ty\":\"gf\",\"bm\":0,\"hd\":false,\"e\":{\"a\":0,\"k\":[-227.438,178.621],\"ix\":6},\"g\":{\"p\":3,\"k\":{\"a\":0,\"k\":[0,0.9215686274509803,0.9568627450980393,0.9882352941176471,0.655,0.8666666666666667,0.8823529411764706,0.9019607843137255,1,0.8117647058823529,0.8117647058823529,0.8117647058823529],\"ix\":9}},\"t\":1,\"a\":{\"a\":0,\"k\":0},\"h\":{\"a\":0,\"k\":0},\"s\":{\"a\":0,\"k\":[-271.536,175.151],\"ix\":5},\"r\":1,\"o\":{\"a\":0,\"k\":100,\"ix\":10}},{\"ty\":\"tr\",\"a\":{\"a\":0,\"k\":[0,0],\"ix\":1},\"s\":{\"a\":0,\"k\":[100,100],\"ix\":3},\"sk\":{\"a\":0,\"k\":0,\"ix\":4},\"p\":{\"a\":0,\"k\":[0,0],\"ix\":2},\"r\":{\"a\":0,\"k\":0,\"ix\":6},\"sa\":{\"a\":0,\"k\":0,\"ix\":5},\"o\":{\"a\":0,\"k\":100,\"ix\":7}}]}],\"ind\":2,\"parent\":7},{\"ty\":4,\"sr\":1,\"st\":0,\"op\":300,\"ip\":0,\"hd\":false,\"ddd\":0,\"bm\":0,\"hasMask\":false,\"ao\":0,\"ks\":{\"a\":{\"a\":0,\"k\":[-158,-120.5,0],\"ix\":1},\"s\":{\"a\":1,\"k\":[{\"o\":{\"x\":0.167,\"y\":0.167},\"i\":{\"x\":0.667,\"y\":1},\"s\":[100,100,100],\"t\":36},{\"o\":{\"x\":0.333,\"y\":0},\"i\":{\"x\":0.833,\"y\":0.833},\"s\":[100,0,100],\"t\":41},{\"s\":[100,100,100],\"t\":46}],\"ix\":6},\"sk\":{\"a\":0,\"k\":0},\"p\":{\"a\":0,\"k\":[120,-120.5,0],\"ix\":2},\"r\":{\"a\":0,\"k\":0,\"ix\":10},\"sa\":{\"a\":0,\"k\":0},\"o\":{\"a\":0,\"k\":100,\"ix\":11}},\"ef\":[],\"shapes\":[{\"ty\":\"gr\",\"bm\":0,\"hd\":false,\"ix\":1,\"cix\":2,\"np\":3,\"it\":[{\"ty\":\"rc\",\"bm\":0,\"hd\":false,\"d\":1,\"p\":{\"a\":0,\"k\":[0,0],\"ix\":3},\"r\":{\"a\":0,\"k\":20,\"ix\":4},\"s\":{\"a\":0,\"k\":[36,93],\"ix\":2}},{\"ty\":\"st\",\"bm\":0,\"hd\":false,\"lc\":1,\"lj\":1,\"ml\":4,\"o\":{\"a\":0,\"k\":100,\"ix\":4},\"w\":{\"a\":0,\"k\":0,\"ix\":5},\"c\":{\"a\":0,\"k\":[1,1,1],\"ix\":3}},{\"ty\":\"fl\",\"bm\":0,\"hd\":false,\"c\":{\"a\":0,\"k\":[0.4941,0.5412,1],\"ix\":4},\"r\":1,\"o\":{\"a\":0,\"k\":100,\"ix\":5}},{\"ty\":\"tr\",\"a\":{\"a\":0,\"k\":[0,0],\"ix\":1},\"s\":{\"a\":0,\"k\":[100,100],\"ix\":3},\"sk\":{\"a\":0,\"k\":0,\"ix\":4},\"p\":{\"a\":0,\"k\":[-158,-120.5],\"ix\":2},\"r\":{\"a\":0,\"k\":0,\"ix\":6},\"sa\":{\"a\":0,\"k\":0,\"ix\":5},\"o\":{\"a\":0,\"k\":100,\"ix\":7}}]}],\"ind\":3,\"parent\":5},{\"ty\":4,\"sr\":1,\"st\":0,\"op\":300,\"ip\":0,\"hd\":false,\"ddd\":0,\"bm\":0,\"hasMask\":false,\"ao\":0,\"ks\":{\"a\":{\"a\":0,\"k\":[-158,-120.5,0],\"ix\":1},\"s\":{\"a\":1,\"k\":[{\"o\":{\"x\":0.167,\"y\":0.167},\"i\":{\"x\":0.667,\"y\":1},\"s\":[100,100,100],\"t\":36},{\"o\":{\"x\":0.333,\"y\":0},\"i\":{\"x\":0.833,\"y\":0.833},\"s\":[100,0,100],\"t\":41},{\"s\":[100,100,100],\"t\":46}],\"ix\":6},\"sk\":{\"a\":0,\"k\":0},\"p\":{\"a\":0,\"k\":[-158,-120.5,0],\"ix\":2},\"r\":{\"a\":0,\"k\":0,\"ix\":10},\"sa\":{\"a\":0,\"k\":0},\"o\":{\"a\":0,\"k\":100,\"ix\":11}},\"ef\":[],\"shapes\":[{\"ty\":\"gr\",\"bm\":0,\"hd\":false,\"ix\":1,\"cix\":2,\"np\":3,\"it\":[{\"ty\":\"rc\",\"bm\":0,\"hd\":false,\"d\":1,\"p\":{\"a\":0,\"k\":[0,0],\"ix\":3},\"r\":{\"a\":0,\"k\":20,\"ix\":4},\"s\":{\"a\":0,\"k\":[36,93],\"ix\":2}},{\"ty\":\"st\",\"bm\":0,\"hd\":false,\"lc\":1,\"lj\":1,\"ml\":4,\"o\":{\"a\":0,\"k\":100,\"ix\":4},\"w\":{\"a\":0,\"k\":0,\"ix\":5},\"c\":{\"a\":0,\"k\":[1,1,1],\"ix\":3}},{\"ty\":\"fl\",\"bm\":0,\"hd\":false,\"c\":{\"a\":0,\"k\":[0.4941,0.5412,1],\"ix\":4},\"r\":1,\"o\":{\"a\":0,\"k\":100,\"ix\":5}},{\"ty\":\"tr\",\"a\":{\"a\":0,\"k\":[0,0],\"ix\":1},\"s\":{\"a\":0,\"k\":[100,100],\"ix\":3},\"sk\":{\"a\":0,\"k\":0,\"ix\":4},\"p\":{\"a\":0,\"k\":[-158,-120.5],\"ix\":2},\"r\":{\"a\":0,\"k\":0,\"ix\":6},\"sa\":{\"a\":0,\"k\":0,\"ix\":5},\"o\":{\"a\":0,\"k\":100,\"ix\":7}}]}],\"ind\":4,\"parent\":5},{\"ty\":4,\"sr\":1,\"st\":0,\"op\":300,\"ip\":0,\"hd\":false,\"ddd\":0,\"bm\":0,\"hasMask\":false,\"ao\":0,\"ks\":{\"a\":{\"a\":0,\"k\":[-16.492,-119,0],\"ix\":1},\"s\":{\"a\":0,\"k\":[100,100,100],\"ix\":6},\"sk\":{\"a\":0,\"k\":0},\"p\":{\"a\":1,\"k\":[{\"o\":{\"x\":0.333,\"y\":0},\"i\":{\"x\":0.667,\"y\":1},\"s\":[-16.492,-119,0],\"t\":7,\"ti\":[-6.794,3.569,0],\"to\":[6.794,-3.569,0]},{\"o\":{\"x\":0.167,\"y\":0.167},\"i\":{\"x\":0.833,\"y\":0.833},\"s\":[24.269,-140.413,0],\"t\":45,\"ti\":[0,0,0],\"to\":[0,0,0]},{\"o\":{\"x\":0.333,\"y\":0},\"i\":{\"x\":0.667,\"y\":1},\"s\":[24.269,-140.413,0],\"t\":53,\"ti\":[6.794,-3.569,0],\"to\":[-6.794,3.569,0]},{\"s\":[-16.492,-119,0],\"t\":79}],\"ix\":2},\"r\":{\"a\":0,\"k\":0,\"ix\":10},\"sa\":{\"a\":0,\"k\":0},\"o\":{\"a\":0,\"k\":100,\"ix\":11}},\"ef\":[],\"shapes\":[{\"ty\":\"gr\",\"bm\":0,\"hd\":false,\"ix\":1,\"cix\":2,\"np\":3,\"it\":[{\"ty\":\"sh\",\"bm\":0,\"hd\":false,\"ix\":1,\"d\":1,\"ks\":{\"a\":1,\"k\":[{\"o\":{\"x\":0.167,\"y\":0.167},\"i\":{\"x\":0.667,\"y\":1},\"s\":[{\"c\":true,\"i\":[[0,0.5],[80.5,-54],[0,0],[-3,82.5],[43.5,1]],\"o\":[[-1.383,5.531],[0,0],[0,0],[1.508,-41.476],[-43.5,-1]],\"v\":[[9,-199.75],[-65,-40.5],[158,-40.5],[210,-121],[152.25,-199.5]]}],\"t\":7},{\"o\":{\"x\":0.333,\"y\":0},\"i\":{\"x\":0.667,\"y\":1},\"s\":[{\"c\":true,\"i\":[[0,0.5],[80.5,-54],[0,0],[-3,82.5],[43.5,1]],\"o\":[[-1.383,5.531],[0,0],[0,0],[1.508,-41.476],[-43.5,-1]],\"v\":[[31.083,-199.182],[-42.917,-39.932],[158,-40.5],[210,-121],[152.25,-199.5]]}],\"t\":45},{\"o\":{\"x\":0.333,\"y\":0},\"i\":{\"x\":0.833,\"y\":0.833},\"s\":[{\"c\":true,\"i\":[[0,0.5],[80.5,-54],[0,0],[-3,82.5],[43.5,1]],\"o\":[[-1.383,5.531],[0,0],[0,0],[1.508,-41.476],[-43.5,-1]],\"v\":[[31.083,-199.182],[-42.917,-39.932],[158,-40.5],[210,-121],[152.25,-199.5]]}],\"t\":53},{\"s\":[{\"c\":true,\"i\":[[0,0.5],[80.5,-54],[0,0],[-3,82.5],[43.5,1]],\"o\":[[-1.383,5.531],[0,0],[0,0],[1.508,-41.476],[-43.5,-1]],\"v\":[[9,-199.75],[-65,-40.5],[158,-40.5],[210,-121],[152.25,-199.5]]}],\"t\":79}],\"ix\":2}},{\"ty\":\"st\",\"bm\":0,\"hd\":false,\"lc\":1,\"lj\":1,\"ml\":4,\"o\":{\"a\":0,\"k\":100,\"ix\":4},\"w\":{\"a\":0,\"k\":0,\"ix\":5},\"c\":{\"a\":0,\"k\":[1,1,1],\"ix\":3}},{\"ty\":\"fl\",\"bm\":0,\"hd\":false,\"c\":{\"a\":0,\"k\":[0.2275,0.2275,0.2275],\"ix\":4},\"r\":1,\"o\":{\"a\":0,\"k\":100,\"ix\":5}},{\"ty\":\"tr\",\"a\":{\"a\":0,\"k\":[0,0],\"ix\":1},\"s\":{\"a\":0,\"k\":[100,100],\"ix\":3},\"sk\":{\"a\":0,\"k\":0,\"ix\":4},\"p\":{\"a\":0,\"k\":[0,0],\"ix\":2},\"r\":{\"a\":0,\"k\":0,\"ix\":6},\"sa\":{\"a\":0,\"k\":0,\"ix\":5},\"o\":{\"a\":0,\"k\":100,\"ix\":7}}]},{\"ty\":\"gr\",\"bm\":0,\"hd\":false,\"ix\":2,\"cix\":2,\"np\":3,\"it\":[{\"ty\":\"rc\",\"bm\":0,\"hd\":false,\"d\":1,\"p\":{\"a\":0,\"k\":[0,0],\"ix\":3},\"r\":{\"a\":0,\"k\":64,\"ix\":4},\"s\":{\"a\":0,\"k\":[441,162],\"ix\":2}},{\"ty\":\"st\",\"bm\":0,\"hd\":false,\"lc\":1,\"lj\":1,\"ml\":4,\"o\":{\"a\":0,\"k\":100,\"ix\":4},\"w\":{\"a\":0,\"k\":0,\"ix\":5},\"c\":{\"a\":0,\"k\":[1,1,1],\"ix\":3}},{\"ty\":\"fl\",\"bm\":0,\"hd\":false,\"c\":{\"a\":0,\"k\":[0.1333,0.1333,0.1333],\"ix\":4},\"r\":1,\"o\":{\"a\":0,\"k\":100,\"ix\":5}},{\"ty\":\"tr\",\"a\":{\"a\":0,\"k\":[0,0],\"ix\":1},\"s\":{\"a\":0,\"k\":[102.759,100],\"ix\":3},\"sk\":{\"a\":0,\"k\":0,\"ix\":4},\"p\":{\"a\":0,\"k\":[-16.5,-119],\"ix\":2},\"r\":{\"a\":0,\"k\":0,\"ix\":6},\"sa\":{\"a\":0,\"k\":0,\"ix\":5},\"o\":{\"a\":0,\"k\":100,\"ix\":7}}]}],\"ind\":5,\"parent\":6},{\"ty\":4,\"sr\":1,\"st\":0,\"op\":300,\"ip\":0,\"hd\":false,\"ddd\":0,\"bm\":0,\"hasMask\":false,\"ao\":0,\"ks\":{\"a\":{\"a\":0,\"k\":[-19.719,9.59,0],\"ix\":1},\"s\":{\"a\":0,\"k\":[100,100,100],\"ix\":6},\"sk\":{\"a\":0,\"k\":0},\"p\":{\"a\":1,\"k\":[{\"o\":{\"x\":0.333,\"y\":0},\"i\":{\"x\":0.667,\"y\":1},\"s\":[-19.719,9.59,0],\"t\":7,\"ti\":[0,0,0],\"to\":[0,0,0]},{\"o\":{\"x\":0.167,\"y\":0.167},\"i\":{\"x\":0.833,\"y\":0.833},\"s\":[-19.719,45.59,0],\"t\":47,\"ti\":[0,0,0],\"to\":[0,0,0]},{\"o\":{\"x\":0.333,\"y\":0},\"i\":{\"x\":0.667,\"y\":1},\"s\":[-19.719,45.59,0],\"t\":53,\"ti\":[0,0,0],\"to\":[0,0,0]},{\"s\":[-19.719,9.59,0],\"t\":79}],\"ix\":2},\"r\":{\"a\":1,\"k\":[{\"o\":{\"x\":0.333,\"y\":0},\"i\":{\"x\":0.667,\"y\":1},\"s\":[0],\"t\":7},{\"o\":{\"x\":0.333,\"y\":0},\"i\":{\"x\":0.667,\"y\":1},\"s\":[-9],\"t\":28},{\"s\":[0],\"t\":79}],\"ix\":10},\"sa\":{\"a\":0,\"k\":0},\"o\":{\"a\":0,\"k\":100,\"ix\":11}},\"ef\":[],\"shapes\":[{\"ty\":\"gr\",\"bm\":0,\"hd\":false,\"ix\":3,\"cix\":2,\"np\":3,\"it\":[{\"ty\":\"sh\",\"bm\":0,\"hd\":false,\"ix\":1,\"d\":1,\"ks\":{\"a\":0,\"k\":{\"c\":true,\"i\":[[42.021,64.812],[78,-156],[-182,-20],[0,0],[-35.843,52.428]],\"o\":[[-118,-182],[-28.425,56.851],[34.319,3.771],[0,0],[26.995,-39.487]],\"v\":[[242,-226],[-284,-218],[-178,14],[140,16],[250.406,-40.457]]},\"ix\":2}},{\"ty\":\"st\",\"bm\":0,\"hd\":false,\"lc\":1,\"lj\":1,\"ml\":4,\"o\":{\"a\":0,\"k\":100,\"ix\":4},\"w\":{\"a\":0,\"k\":0,\"ix\":5},\"c\":{\"a\":0,\"k\":[1,1,1],\"ix\":3}},{\"ty\":\"gf\",\"bm\":0,\"hd\":false,\"e\":{\"a\":0,\"k\":[198,-58],\"ix\":6},\"g\":{\"p\":3,\"k\":{\"a\":0,\"k\":[0,0.9215686274509803,0.9568627450980393,0.9882352941176471,0.655,0.8666666666666667,0.8823529411764706,0.9019607843137255,1,0.8117647058823529,0.8117647058823529,0.8117647058823529],\"ix\":9}},\"t\":1,\"a\":{\"a\":0,\"k\":0},\"h\":{\"a\":0,\"k\":0},\"s\":{\"a\":0,\"k\":[-296,-60],\"ix\":5},\"r\":1,\"o\":{\"a\":0,\"k\":100,\"ix\":10}},{\"ty\":\"tr\",\"a\":{\"a\":0,\"k\":[0,0],\"ix\":1},\"s\":{\"a\":0,\"k\":[100,100],\"ix\":3},\"sk\":{\"a\":0,\"k\":0,\"ix\":4},\"p\":{\"a\":0,\"k\":[0,0],\"ix\":2},\"r\":{\"a\":0,\"k\":0,\"ix\":6},\"sa\":{\"a\":0,\"k\":0,\"ix\":5},\"o\":{\"a\":0,\"k\":100,\"ix\":7}}]}],\"ind\":6,\"parent\":7},{\"ty\":4,\"sr\":1,\"st\":0,\"op\":300,\"ip\":0,\"hd\":false,\"ddd\":0,\"bm\":0,\"hasMask\":false,\"ao\":0,\"ks\":{\"a\":{\"a\":0,\"k\":[-20.704,175.322,0],\"ix\":1},\"s\":{\"a\":0,\"k\":[100,100,100],\"ix\":6},\"sk\":{\"a\":0,\"k\":0},\"p\":{\"a\":1,\"k\":[{\"o\":{\"x\":0.333,\"y\":0},\"i\":{\"x\":0.667,\"y\":1},\"s\":[519.296,715.322,0],\"t\":0,\"ti\":[0,0,0],\"to\":[0,0,0]},{\"o\":{\"x\":0.333,\"y\":0},\"i\":{\"x\":0.667,\"y\":1},\"s\":[519.296,635.322,0],\"t\":45,\"ti\":[0,0,0],\"to\":[0,0,0]},{\"s\":[519.296,715.322,0],\"t\":90}],\"ix\":2},\"r\":{\"a\":0,\"k\":0,\"ix\":10},\"sa\":{\"a\":0,\"k\":0},\"o\":{\"a\":0,\"k\":100,\"ix\":11}},\"ef\":[],\"shapes\":[{\"ty\":\"gr\",\"bm\":0,\"hd\":false,\"ix\":1,\"cix\":2,\"np\":3,\"it\":[{\"ty\":\"el\",\"bm\":0,\"hd\":false,\"d\":1,\"p\":{\"a\":0,\"k\":[0,0],\"ix\":3},\"s\":{\"a\":0,\"k\":[227,65],\"ix\":2}},{\"ty\":\"st\",\"bm\":0,\"hd\":false,\"lc\":1,\"lj\":1,\"ml\":4,\"o\":{\"a\":0,\"k\":100,\"ix\":4},\"w\":{\"a\":0,\"k\":1,\"ix\":5},\"c\":{\"a\":0,\"k\":[0.5765,0.5765,0.5765],\"ix\":3}},{\"ty\":\"fl\",\"bm\":0,\"hd\":false,\"c\":{\"a\":0,\"k\":[0.8196,0.8196,0.8196],\"ix\":4},\"r\":1,\"o\":{\"a\":0,\"k\":100,\"ix\":5}},{\"ty\":\"tr\",\"a\":{\"a\":0,\"k\":[0,0],\"ix\":1},\"s\":{\"a\":0,\"k\":[100,100],\"ix\":3},\"sk\":{\"a\":0,\"k\":0,\"ix\":4},\"p\":{\"a\":0,\"k\":[-23.5,68.5],\"ix\":2},\"r\":{\"a\":0,\"k\":0,\"ix\":6},\"sa\":{\"a\":0,\"k\":0,\"ix\":5},\"o\":{\"a\":0,\"k\":100,\"ix\":7}}]},{\"ty\":\"gr\",\"bm\":0,\"hd\":false,\"ix\":2,\"cix\":2,\"np\":3,\"it\":[{\"ty\":\"sh\",\"bm\":0,\"hd\":false,\"ix\":1,\"d\":1,\"ks\":{\"a\":0,\"k\":{\"c\":true,\"i\":[[51,0],[15.678,-82.948],[-49.731,-49.359],[-13.15,-0.292],[-37.729,38.101],[10.258,44.845]],\"o\":[[-12.374,0],[-8.179,43.273],[38.555,38.266],[13.544,0.301],[45.84,-46.291],[-15.181,-66.366]],\"v\":[[-27,31],[-179.678,102.948],[-132.269,283.359],[-25,320],[91.483,284.497],[137.742,101.155]]},\"ix\":2}},{\"ty\":\"st\",\"bm\":0,\"hd\":false,\"lc\":1,\"lj\":1,\"ml\":4,\"o\":{\"a\":0,\"k\":100,\"ix\":4},\"w\":{\"a\":0,\"k\":0,\"ix\":5},\"c\":{\"a\":0,\"k\":[1,1,1],\"ix\":3}},{\"ty\":\"gf\",\"bm\":0,\"hd\":false,\"e\":{\"a\":0,\"k\":[86,146],\"ix\":6},\"g\":{\"p\":3,\"k\":{\"a\":0,\"k\":[0,0.9215686274509803,0.9568627450980393,0.9882352941176471,0.655,0.8666666666666667,0.8823529411764706,0.9019607843137255,1,0.8117647058823529,0.8117647058823529,0.8117647058823529],\"ix\":9}},\"t\":1,\"a\":{\"a\":0,\"k\":0},\"h\":{\"a\":0,\"k\":0},\"s\":{\"a\":0,\"k\":[-166,148],\"ix\":5},\"r\":1,\"o\":{\"a\":0,\"k\":100,\"ix\":10}},{\"ty\":\"tr\",\"a\":{\"a\":0,\"k\":[0,0],\"ix\":1},\"s\":{\"a\":0,\"k\":[100,100],\"ix\":3},\"sk\":{\"a\":0,\"k\":0,\"ix\":4},\"p\":{\"a\":0,\"k\":[0,0],\"ix\":2},\"r\":{\"a\":0,\"k\":0,\"ix\":6},\"sa\":{\"a\":0,\"k\":0,\"ix\":5},\"o\":{\"a\":0,\"k\":100,\"ix\":7}}]}],\"ind\":7},{\"ty\":4,\"sr\":1,\"st\":0,\"op\":300,\"ip\":0,\"hd\":false,\"ddd\":0,\"bm\":0,\"hasMask\":false,\"ao\":0,\"ks\":{\"a\":{\"a\":0,\"k\":[-305.5,-118,0],\"ix\":1},\"s\":{\"a\":0,\"k\":[100,100,100],\"ix\":6},\"sk\":{\"a\":0,\"k\":0},\"p\":{\"a\":1,\"k\":[{\"o\":{\"x\":0.333,\"y\":0},\"i\":{\"x\":0.667,\"y\":1},\"s\":[263.5,-118,0],\"t\":7,\"ti\":[0,0,0],\"to\":[0,0,0]},{\"o\":{\"x\":0.333,\"y\":0},\"i\":{\"x\":0.667,\"y\":1},\"s\":[247.381,-117.593,0],\"t\":49,\"ti\":[0,0,0],\"to\":[0,0,0]},{\"s\":[263.5,-118,0],\"t\":79}],\"ix\":2},\"r\":{\"a\":0,\"k\":0,\"ix\":10},\"sa\":{\"a\":0,\"k\":0},\"o\":{\"a\":0,\"k\":100,\"ix\":11}},\"ef\":[],\"shapes\":[{\"ty\":\"gr\",\"bm\":0,\"hd\":false,\"ix\":1,\"cix\":2,\"np\":3,\"it\":[{\"ty\":\"el\",\"bm\":0,\"hd\":false,\"d\":1,\"p\":{\"a\":0,\"k\":[0,0],\"ix\":3},\"s\":{\"a\":0,\"k\":[111,138],\"ix\":2}},{\"ty\":\"st\",\"bm\":0,\"hd\":false,\"lc\":1,\"lj\":1,\"ml\":4,\"o\":{\"a\":0,\"k\":100,\"ix\":4},\"w\":{\"a\":0,\"k\":0,\"ix\":5},\"c\":{\"a\":0,\"k\":[1,1,1],\"ix\":3}},{\"ty\":\"fl\",\"bm\":0,\"hd\":false,\"c\":{\"a\":0,\"k\":[0.8824,0.8824,0.8824],\"ix\":4},\"r\":1,\"o\":{\"a\":0,\"k\":100,\"ix\":5}},{\"ty\":\"tr\",\"a\":{\"a\":0,\"k\":[0,0],\"ix\":1},\"s\":{\"a\":0,\"k\":[100,100],\"ix\":3},\"sk\":{\"a\":0,\"k\":0,\"ix\":4},\"p\":{\"a\":0,\"k\":[-305.5,-118],\"ix\":2},\"r\":{\"a\":0,\"k\":0,\"ix\":6},\"sa\":{\"a\":0,\"k\":0,\"ix\":5},\"o\":{\"a\":0,\"k\":100,\"ix\":7}}]}],\"ind\":8,\"parent\":6},{\"ty\":4,\"sr\":1,\"st\":0,\"op\":300,\"ip\":0,\"hd\":false,\"ddd\":0,\"bm\":0,\"hasMask\":false,\"ao\":0,\"ks\":{\"a\":{\"a\":0,\"k\":[-305.5,-118,0],\"ix\":1},\"s\":{\"a\":0,\"k\":[100,100,100],\"ix\":6},\"sk\":{\"a\":0,\"k\":0},\"p\":{\"a\":1,\"k\":[{\"o\":{\"x\":0.333,\"y\":0},\"i\":{\"x\":0.667,\"y\":1},\"s\":[-305.5,-118,0],\"t\":7,\"ti\":[0,0,0],\"to\":[0,0,0]},{\"o\":{\"x\":0.333,\"y\":0},\"i\":{\"x\":0.667,\"y\":1},\"s\":[-321.619,-117.593,0],\"t\":49,\"ti\":[0,0,0],\"to\":[0,0,0]},{\"s\":[-305.5,-118,0],\"t\":79}],\"ix\":2},\"r\":{\"a\":0,\"k\":0,\"ix\":10},\"sa\":{\"a\":0,\"k\":0},\"o\":{\"a\":0,\"k\":100,\"ix\":11}},\"ef\":[],\"shapes\":[{\"ty\":\"gr\",\"bm\":0,\"hd\":false,\"ix\":1,\"cix\":2,\"np\":3,\"it\":[{\"ty\":\"el\",\"bm\":0,\"hd\":false,\"d\":1,\"p\":{\"a\":0,\"k\":[0,0],\"ix\":3},\"s\":{\"a\":0,\"k\":[111,138],\"ix\":2}},{\"ty\":\"st\",\"bm\":0,\"hd\":false,\"lc\":1,\"lj\":1,\"ml\":4,\"o\":{\"a\":0,\"k\":100,\"ix\":4},\"w\":{\"a\":0,\"k\":0,\"ix\":5},\"c\":{\"a\":0,\"k\":[1,1,1],\"ix\":3}},{\"ty\":\"fl\",\"bm\":0,\"hd\":false,\"c\":{\"a\":0,\"k\":[0.8824,0.8824,0.8824],\"ix\":4},\"r\":1,\"o\":{\"a\":0,\"k\":100,\"ix\":5}},{\"ty\":\"tr\",\"a\":{\"a\":0,\"k\":[0,0],\"ix\":1},\"s\":{\"a\":0,\"k\":[100,100],\"ix\":3},\"sk\":{\"a\":0,\"k\":0,\"ix\":4},\"p\":{\"a\":0,\"k\":[-305.5,-118],\"ix\":2},\"r\":{\"a\":0,\"k\":0,\"ix\":6},\"sa\":{\"a\":0,\"k\":0,\"ix\":5},\"o\":{\"a\":0,\"k\":100,\"ix\":7}}]}],\"ind\":9,\"parent\":6},{\"ty\":4,\"sr\":1,\"st\":0,\"op\":300,\"ip\":0,\"hd\":false,\"ddd\":0,\"bm\":0,\"hasMask\":false,\"ao\":0,\"ks\":{\"a\":{\"a\":0,\"k\":[-17.5,380.5,0],\"ix\":1},\"s\":{\"a\":1,\"k\":[{\"o\":{\"x\":0.333,\"y\":0},\"i\":{\"x\":0.667,\"y\":1},\"s\":[100,100,100],\"t\":0},{\"o\":{\"x\":0.333,\"y\":0},\"i\":{\"x\":0.667,\"y\":1},\"s\":[108,108,100],\"t\":45},{\"s\":[100,100,100],\"t\":90}],\"ix\":6},\"sk\":{\"a\":0,\"k\":0},\"p\":{\"a\":0,\"k\":[523.5,919.5,0],\"ix\":2},\"r\":{\"a\":0,\"k\":0,\"ix\":10},\"sa\":{\"a\":0,\"k\":0},\"o\":{\"a\":0,\"k\":60,\"ix\":11}},\"ef\":[],\"shapes\":[{\"ty\":\"gr\",\"bm\":0,\"hd\":false,\"ix\":1,\"cix\":2,\"np\":3,\"it\":[{\"ty\":\"el\",\"bm\":0,\"hd\":false,\"d\":1,\"p\":{\"a\":0,\"k\":[0,0],\"ix\":3},\"s\":{\"a\":0,\"k\":[249,59],\"ix\":2}},{\"ty\":\"st\",\"bm\":0,\"hd\":false,\"lc\":1,\"lj\":1,\"ml\":4,\"o\":{\"a\":0,\"k\":100,\"ix\":4},\"w\":{\"a\":0,\"k\":0,\"ix\":5},\"c\":{\"a\":0,\"k\":[1,1,1],\"ix\":3}},{\"ty\":\"fl\",\"bm\":0,\"hd\":false,\"c\":{\"a\":0,\"k\":[0.7686,0.7686,0.7686],\"ix\":4},\"r\":1,\"o\":{\"a\":0,\"k\":100,\"ix\":5}},{\"ty\":\"tr\",\"a\":{\"a\":0,\"k\":[0,0],\"ix\":1},\"s\":{\"a\":0,\"k\":[100,100],\"ix\":3},\"sk\":{\"a\":0,\"k\":0,\"ix\":4},\"p\":{\"a\":0,\"k\":[-17.5,380.5],\"ix\":2},\"r\":{\"a\":0,\"k\":0,\"ix\":6},\"sa\":{\"a\":0,\"k\":0,\"ix\":5},\"o\":{\"a\":0,\"k\":100,\"ix\":7}}]}],\"ind\":10}]}]}";

  // ── Orbe liquido (indicador de escritura) ───────────────────────────────────────────────
  // Adaptacion del efecto de widget/animation.html ("Liquid Orb"): aquel es una pagina WebGL
  // de 86 KB de shader; aqui se reescribe la idea (flujo fbm + esfera con borde de vidrio y
  // brillo especular) en ~30 lineas de GLSL con la paleta del producto. Un solo canvas y un
  // solo contexto WebGL reutilizados entre renders — cada sondeo reconstruye la vista y crear
  // un contexto nuevo cada 2,5 s agotaria el limite del navegador. El tiempo se ancla a
  // state.typingSince para que el fluido continue en vez de reiniciarse en cada render.
  // Sin WebGL (o si el contexto falla al crear el programa): los tres puntos de siempre.
  // A PROPOSITO no respeta prefers-reduced-motion: es un indicador de estado del mismo tipo
  // que los 3 puntos (que tampoco lo respetan, ver el media query en CSS) — pequeño, vive solo
  // mientras se espera la respuesta, y remplaza una animacion por otra, no agrega movimiento
  // nuevo a la pagina. Lo decorativo (halos, flotacion, parpadeo) si se apaga ahi.
  // ── Orbe WebGPU: copia de widget/animation.html ─────────────────────────────────────────
  // El shader WGSL es EL MISMO archivo (solo sin comentarios) y los uniforms son la semilla
  // "thinking" tal cual — el look es identico a la referencia por construccion, no una
  // imitacion. El camino "ribbon" (indice de estilo 24) no se porta: ninguno de los dos
  // estados lo usa (ambos son estilo 19), asi que sus tres pipelines sobraban.
  // WebGPU no existe en Firefox estable ni en Safari viejo: ahi cae al orbe WebGL de abajo,
  // y sin WebGL quedan los tres puntos. Nadie se queda sin indicador.
  const ORB_WGSL = "struct Uniforms {\n  size:           vec2<f32>,\n  time:           f32,\n  speed:          f32,\n  radius:         f32,\n  zoom:           f32,\n  warp:           f32,\n  ridgeAmt:       f32,\n  sharp:          f32,\n  shade:          f32,\n  sheen:          f32,\n  gloss:          f32,\n  shellMidAlpha:  f32,\n  shellEdgeAlpha: f32,\n  exposure:       f32,\n  style:          f32,\n  edgeSoftness:   f32,\n  edgeGlow:       f32,\n  paletteCount:   f32,\n  glassEnabled:   f32,\n  glassOpacity:   f32,\n  contourDeform:  f32,\n  bandDensity:    f32,\n  chromaticShift: f32,\n  metalScale:     f32,\n  metalStretch:   f32,\n  metalAngle:     f32,\n  metalOffset:    f32,\n  metalPhase:     f32,\n  metalEvolution: f32,\n  metalRoughness: f32,\n  metalDepth:     f32,\n  particleDensity: f32,\n  ribbonCount:     f32,\n  ribbonWidth:     f32,\n  ribbonTwist:     f32,\n  ribbonFold:      f32,\n  ribbonBreath:    f32,\n  particleSize:    f32,\n  particleBloom:   f32,\n  colorA:         vec4<f32>,\n  colorB:         vec4<f32>,\n  colorC:         vec4<f32>,\n  colorD:         vec4<f32>,\n  highlightColor: vec4<f32>,\n  shellInner:     vec4<f32>,\n  shellMid:       vec4<f32>,\n  shellEdge:      vec4<f32>,\n  sheenColor:     vec4<f32>,\n  specColor:      vec4<f32>,\n  canvasColor:    vec4<f32>,\n  glowColor:      vec4<f32>,\n  paletteStop0:    vec4<f32>,\n  paletteStop1:    vec4<f32>,\n  paletteStop2:    vec4<f32>,\n  paletteStop3:    vec4<f32>,\n  paletteStop4:    vec4<f32>,\n  paletteStop5:    vec4<f32>,\n  paletteStop6:    vec4<f32>,\n  paletteStop7:    vec4<f32>,\n  paletteStop8:    vec4<f32>,\n  paletteStop9:    vec4<f32>,\n  paletteStop10:   vec4<f32>,\n  paletteStop11:   vec4<f32>,\n};\n@group(0) @binding(0) var<uniform> u: Uniforms;\nfn mfEdgeD(soft: f32) -> f32 {\n  return soft - 0.005;\n}\nfn mfEdgeGlow(col: vec3<f32>, uv: vec2<f32>, ctr: vec2<f32>, rad: f32,\n              soft: f32, glow: f32, glowRGB: vec3<f32>) -> vec3<f32> {\n  if (glow <= 0.0) { return col; }\n  let r = length(uv - ctr);\n  let outside = smoothstep(rad - max(soft, 0.0005), rad + max(soft, 0.0005), r);\n  return col + glowRGB * (glow * exp(-max(r - rad, 0.0) * 11.0) * outside);\n}\nfn mfRampPick(idx: f32,\n              s0: vec3<f32>, s1: vec3<f32>, s2:  vec3<f32>, s3:  vec3<f32>,\n              s4: vec3<f32>, s5: vec3<f32>, s6:  vec3<f32>, s7:  vec3<f32>,\n              s8: vec3<f32>, s9: vec3<f32>, s10: vec3<f32>, s11: vec3<f32>) -> vec3<f32> {\n  var r = s0;\n  r = select(r, s1,  idx == 1.0);\n  r = select(r, s2,  idx == 2.0);\n  r = select(r, s3,  idx == 3.0);\n  r = select(r, s4,  idx == 4.0);\n  r = select(r, s5,  idx == 5.0);\n  r = select(r, s6,  idx == 6.0);\n  r = select(r, s7,  idx == 7.0);\n  r = select(r, s8,  idx == 8.0);\n  r = select(r, s9,  idx == 9.0);\n  r = select(r, s10, idx == 10.0);\n  r = select(r, s11, idx == 11.0);\n  return r;\n}\nfn mfRampCyc(tIn: f32, n: f32,\n             s0: vec3<f32>, s1: vec3<f32>, s2:  vec3<f32>, s3:  vec3<f32>,\n             s4: vec3<f32>, s5: vec3<f32>, s6:  vec3<f32>, s7:  vec3<f32>,\n             s8: vec3<f32>, s9: vec3<f32>, s10: vec3<f32>, s11: vec3<f32>) -> vec3<f32> {\n  let k  = clamp(floor(n + 0.5), 1.0, 12.0);\n  let x  = fract(tIn) * k;\n  let i0 = min(floor(x), k - 1.0);\n  let i1 = select(i0 + 1.0, 0.0, i0 + 1.0 >= k);\n  return mix(mfRampPick(i0, s0, s1, s2, s3, s4, s5, s6, s7, s8, s9, s10, s11),\n             mfRampPick(i1, s0, s1, s2, s3, s4, s5, s6, s7, s8, s9, s10, s11),\n             x - i0);\n}\nfn mfRampLin(tIn: f32, n: f32,\n             s0: vec3<f32>, s1: vec3<f32>, s2:  vec3<f32>, s3:  vec3<f32>,\n             s4: vec3<f32>, s5: vec3<f32>, s6:  vec3<f32>, s7:  vec3<f32>,\n             s8: vec3<f32>, s9: vec3<f32>, s10: vec3<f32>, s11: vec3<f32>) -> vec3<f32> {\n  let k  = clamp(floor(n + 0.5), 1.0, 12.0);\n  let x  = clamp(tIn, 0.0, 1.0) * (k - 1.0);\n  let i0 = clamp(floor(x), 0.0, max(k - 2.0, 0.0));\n  return mix(mfRampPick(i0,     s0, s1, s2, s3, s4, s5, s6, s7, s8, s9, s10, s11),\n             mfRampPick(i0 + 1.0, s0, s1, s2, s3, s4, s5, s6, s7, s8, s9, s10, s11),\n             x - i0);\n}\nstruct MfRamp {\n  n:   f32,\n  s0:  vec3<f32>, s1:  vec3<f32>, s2:  vec3<f32>, s3:  vec3<f32>,\n  s4:  vec3<f32>, s5:  vec3<f32>, s6:  vec3<f32>, s7:  vec3<f32>,\n  s8:  vec3<f32>, s9:  vec3<f32>, s10: vec3<f32>, s11: vec3<f32>,\n};\nfn mfRampOf(n: f32,\n            s0: vec3<f32>, s1: vec3<f32>, s2:  vec3<f32>, s3:  vec3<f32>,\n            s4: vec3<f32>, s5: vec3<f32>, s6:  vec3<f32>, s7:  vec3<f32>,\n            s8: vec3<f32>, s9: vec3<f32>, s10: vec3<f32>, s11: vec3<f32>) -> MfRamp {\n  return MfRamp(n, s0, s1, s2, s3, s4, s5, s6, s7, s8, s9, s10, s11);\n}\nfn mfRampCycR(t: f32, r: MfRamp) -> vec3<f32> {\n  return mfRampCyc(t, r.n, r.s0, r.s1, r.s2, r.s3, r.s4, r.s5,\n                   r.s6, r.s7, r.s8, r.s9, r.s10, r.s11);\n}\nfn mfRampLinR(t: f32, r: MfRamp) -> vec3<f32> {\n  return mfRampLin(t, r.n, r.s0, r.s1, r.s2, r.s3, r.s4, r.s5,\n                   r.s6, r.s7, r.s8, r.s9, r.s10, r.s11);\n}\nconst GL_FU:   f32 = 0.88172043;\nconst GL_BSIG_CLEAR: f32 = 0.01800000;\nconst GL_BSIG_GLASS: f32 = 0.03990000;\nconst GL_KA:  f32 = 6.0;\nconst GL_KG:  f32 = 4.1209;\nconst GL_KWA: f32 = 0.5;\nconst GL_KR:  f32 = 0.32;\nconst GL_GH:  f32 = 1.73205081;\nconst GL_CLEAR_EA: f32 = 0.995;\nconst GL_CLEAR_EB: f32 = 1.04;\nfn lqHash(pIn: vec2<f32>) -> f32 {\n  var p = fract(pIn * vec2<f32>(123.34, 456.21));\n  p = p + vec2<f32>(dot(p, p + vec2<f32>(45.32)));\n  return fract(p.x * p.y);\n}\nfn lqNoise(p: vec2<f32>) -> f32 {\n  let i = floor(p);\n  var f = fract(p);\n  f = f * f * (3.0 - 2.0 * f);\n  return mix(mix(lqHash(i), lqHash(i + vec2<f32>(1.0, 0.0)), f.x),\n             mix(lqHash(i + vec2<f32>(0.0, 1.0)), lqHash(i + vec2<f32>(1.0, 1.0)), f.x), f.y);\n}\nfn lqFbm(pIn: vec2<f32>, bs: f32) -> vec2<f32> {\n  var p = pIn;\n  var s:  f32 = 0.0;\n  var a:  f32 = 0.5;\n  var m:  f32 = 0.0;\n  var vr: f32 = 0.0;\n  let e = -GL_KA * bs * bs;\n  var g: f32 = 1.0;\n  for (var i: i32 = 0; i < 5; i = i + 1) {\n    let b = exp(e * g);\n    s  = s  + a * (0.5 + b * (lqNoise(p) - 0.5));\n    vr = vr + a * a * (1.0 - b * b);\n    m  = m + a;\n    a  = a * 0.5;\n    g  = g * GL_KG;\n    p = vec2<f32>(0.8 * p.x - 0.6 * p.y, 0.6 * p.x + 0.8 * p.y) * 2.03;\n  }\n  return vec2<f32>(s / m, GL_KR * sqrt(vr) / m);\n}\nfn lqRidge(v: f32, k: f32) -> f32 {\n  return pow(clamp(1.0 - abs(v * 2.0 - 1.0), 0.0, 1.0), k);\n}\nfn lqRamp(v: f32, cA: vec3<f32>, cB: vec3<f32>, cC: vec3<f32>, cD: vec3<f32>) -> vec3<f32> {\n  var c = mix(cA, cB, smoothstep(0.0, 0.45, v));\n  c = mix(c, cC, smoothstep(0.38, 0.72, v));\n  c = mix(c, cD, smoothstep(0.68, 1.0, v));\n  return select(c, mfRampLin(v, u.paletteCount,\n                             u.paletteStop0.rgb, u.paletteStop1.rgb, u.paletteStop2.rgb,\n                             u.paletteStop3.rgb, u.paletteStop4.rgb, u.paletteStop5.rgb,\n                             u.paletteStop6.rgb, u.paletteStop7.rgb, u.paletteStop8.rgb,\n                             u.paletteStop9.rgb, u.paletteStop10.rgb, u.paletteStop11.rgb), u.paletteCount > 0.5);\n}\nfn lqRidgeS(vs: vec2<f32>, k: f32) -> f32 {\n  let d = GL_GH * vs.y;\n  return (lqRidge(vs.x - d, k) + 4.0 * lqRidge(vs.x, k) + lqRidge(vs.x + d, k)) / 6.0;\n}\nfn lqStepS(vs: vec2<f32>, a: f32, b: f32) -> f32 {\n  let d = GL_GH * vs.y;\n  return (smoothstep(a, b, vs.x - d) + 4.0 * smoothstep(a, b, vs.x)\n        + smoothstep(a, b, vs.x + d)) / 6.0;\n}\nfn lqPowS(vs: vec2<f32>, k: f32) -> f32 {\n  let d = GL_GH * vs.y;\n  return (pow(clamp(vs.x - d, 0.0, 1.0), k) + 4.0 * pow(clamp(vs.x, 0.0, 1.0), k)\n        + pow(clamp(vs.x + d, 0.0, 1.0), k)) / 6.0;\n}\nfn glsFinishPresetFluid(colorIn: vec3<f32>, p: vec2<f32>) -> vec3<f32> {\n  var color = colorIn;\n  color = mix(color, u.highlightColor.rgb,\n              u.shade * 0.22 * smoothstep(0.15, 1.15, dot(p, vec2<f32>(-0.32, 0.78))));\n  color = color * (1.0 - u.shade * 0.34\n                  * smoothstep(-0.1, 1.2, dot(p, vec2<f32>(0.45, -0.62))));\n  color = color * (1.0 - u.shade * 0.22 * smoothstep(0.72, 1.08, length(p)));\n  return clamp(color, vec3<f32>(0.0), vec3<f32>(1.0));\n}\nfn glsFinishEmissionFluid(colorIn: vec3<f32>, p: vec2<f32>) -> vec3<f32> {\n  var color = colorIn;\n  if (u.glassEnabled > 0.5) {\n    color = mix(color, u.highlightColor.rgb,\n                u.shade * 0.22 * smoothstep(0.15, 1.15, dot(p, vec2<f32>(-0.32, 0.78))));\n  }\n  color = color * (1.0 - u.shade * 0.34\n                  * smoothstep(-0.1, 1.2, dot(p, vec2<f32>(0.45, -0.62))));\n  color = color * (1.0 - u.shade * 0.22 * smoothstep(0.72, 1.08, length(p)));\n  return clamp(color, vec3<f32>(0.0), vec3<f32>(1.0));\n}\nfn glsSiriBand(q: vec2<f32>, drift: f32, phaseOffset: f32, amplitude: f32,\n               mainY: f32, envelope: f32, softness: f32) -> vec2<f32> {\n  let y = amplitude * envelope * sin(q.x * 1.0 + drift + phaseOffset);\n  let distanceToLine = abs(q.y - y);\n  let line = 0.018 / (sqrt(distanceToLine * distanceToLine + softness * softness) + 0.026);\n  let bandDistance = max(0.0, max(q.y - max(mainY, y), min(mainY, y) - q.y));\n  let band = 0.018 / (bandDistance + 0.075);\n  return vec2<f32>(line, band);\n}\nfn glsSiriFluid(p: vec2<f32>, t: f32) -> vec3<f32> {\n  let scale = 0.74 + u.zoom * 0.34;\n  let q = p / scale;\n  let xNorm = q.x;\n  let envelopeBase = cos(1.57079633 * min(abs(0.9 * xNorm), 1.0));\n  let envelope = envelopeBase * envelopeBase;\n  let low = 0.5 + 0.5 * cos(t * 0.37);\n  let mid = 0.5 + 0.5 * sin(t * 0.51 + 1.2);\n  let high = 0.5 + 0.5 * cos(t * 0.73 + 2.1);\n  let drift = t * 2.4;\n  let mainAmplitude = 0.25 + u.ridgeAmt * 0.075 + low * 0.018;\n  let bandAmplitude = mainAmplitude + mid * 0.025 + high * 0.018;\n  let mainY = mainAmplitude * envelope * sin(q.x * 1.1 + drift);\n  let separation = 1.85 + u.warp * 0.2 + mid * 0.28;\n  let softness = 0.035 + (1.0 - u.ridgeAmt) * 0.018 + mid * 0.006;\n  let band0 = glsSiriBand(q, drift, -separation, bandAmplitude, mainY, envelope, softness);\n  let band1 = glsSiriBand(q, drift, -separation * 0.34, bandAmplitude, mainY, envelope, softness);\n  let band2 = glsSiriBand(q, drift, separation * 0.34, bandAmplitude, mainY, envelope, softness);\n  let band3 = glsSiriBand(q, drift, separation, bandAmplitude, mainY, envelope, softness);\n  let w0 = band0.x + band0.y;\n  let w1 = band1.x + band1.y;\n  let w2 = band2.x + band2.y;\n  let w3 = band3.x + band3.y;\n  let total = w0 + w1 + w2 + w3;\n  let dominant0 = w0 * w0;\n  let dominant1 = w1 * w1;\n  let dominant2 = w2 * w2;\n  let dominant3 = w3 * w3;\n  let dominantTotal = dominant0 + dominant1 + dominant2 + dominant3;\n  let spectral = (u.colorA.rgb * dominant0 + u.colorC.rgb * dominant1\n                + u.colorB.rgb * dominant2 + u.colorD.rgb * dominant3)\n                / max(dominantTotal, 0.0001);\n  let energy = (1.0 - exp(-total * 0.58)) * envelope;\n  let mainDistance = abs(q.y - mainY);\n  let whiteCore = exp(-mainDistance * mainDistance / 0.0028) * envelope;\n  let glassFill = select(0.0, 1.0, u.glassEnabled > 0.5);\n  let atmosphere = mix(u.colorD.rgb, u.colorB.rgb,\n                       smoothstep(-0.7, 0.7, q.y)) * 0.018 * glassFill;\n  var color = atmosphere + spectral * energy * 1.14;\n  color = color + u.highlightColor.rgb * whiteCore * (0.18 + 0.1 * low);\n  let emissionMask = mix(smoothstep(0.08, 0.25, energy + whiteCore * 0.12),\n                         1.0, glassFill);\n  color = color * emissionMask;\n  color = color / (vec3<f32>(1.0) + color * 0.18);\n  return glsFinishEmissionFluid(color, p);\n}\nfn glsSpectrumHeight(q: vec2<f32>, t: f32, frequency: f32,\n                     phaseOffset: f32, amplitude: f32) -> f32 {\n  let x = q.x * 2.15;\n  let envelope = pow(4.0 / (4.0 + x * x), 4.0);\n  let breathing = 0.82 + 0.18 * sin(t * 0.48 + phaseOffset * 0.7);\n  let wave = abs(sin(frequency * x - t * 1.36 + phaseOffset));\n  return envelope * amplitude * breathing * (0.28 + 0.72 * wave);\n}\nfn glsSpectrumLayer(q: vec2<f32>, height: f32, softness: f32) -> f32 {\n  return (1.0 - smoothstep(max(height - softness, 0.0), height + softness, abs(q.y)))\n         * smoothstep(0.0, 0.045, height);\n}\nfn glsSpectrumFluid(p: vec2<f32>, t: f32) -> vec3<f32> {\n  let scale = 0.74 + u.zoom * 0.34;\n  let q = p / scale;\n  let amplitude = 0.26 + u.ridgeAmt * 0.27;\n  let frequency = 0.72 + u.warp * 0.095;\n  let softness = 0.026 + (1.0 - u.ridgeAmt) * 0.032;\n  let h0 = glsSpectrumHeight(q, t, frequency * 0.82, -1.2, amplitude * 0.72);\n  let h1 = glsSpectrumHeight(q, t, frequency, 0.45, amplitude);\n  let h2 = glsSpectrumHeight(q, t, frequency * 1.17, 2.05, amplitude * 0.82);\n  let l0 = glsSpectrumLayer(q, h0, softness);\n  let l1 = glsSpectrumLayer(q, h1, softness);\n  let l2 = glsSpectrumLayer(q, h2, softness);\n  let spectrumX = q.x * 2.15;\n  let envelope = pow(4.0 / (4.0 + spectrumX * spectrumX), 4.0);\n  let support = exp(-q.y * q.y / 0.00072) * envelope;\n  let total = l0 + l1 + l2;\n  let spectral = (u.colorB.rgb * l0 + u.colorC.rgb * l1 + u.colorD.rgb * l2)\n                 / max(total, 0.001);\n  let glassFill = select(0.0, 1.0, u.glassEnabled > 0.5);\n  var color = u.colorD.rgb * 0.025 * glassFill\n            + spectral * (1.0 - exp(-total * 0.86));\n  color = color + u.colorA.rgb * support * 0.58;\n  color = color / (vec3<f32>(1.0) + color * 0.2);\n  return glsFinishEmissionFluid(color, p);\n}\nfn glsAuroraLayer(p: vec2<f32>, t: f32, offset: f32) -> f32 {\n  let drift = t * 0.18 + offset * 2.5;\n  let wave1 = sin(p.x * (2.0 + u.warp * 0.13) + drift + offset * 6.0) * 0.25;\n  let wave2 = sin(p.x * 3.7 + drift * 1.3 + offset * 4.0) * 0.12;\n  let wave3 = sin(p.x * 7.2 + drift * 0.7 + offset * 8.0) * 0.055;\n  let noiseValue = lqFbm(vec2<f32>(p.x * 1.6 + drift * 0.35,\n                                   p.y * 0.8 + offset * 3.0), 0.018).x;\n  let center = offset * 0.46 + wave1 + wave2 + wave3\n               + (noiseValue - 0.5) * 0.28;\n  let dist = abs(p.y - center);\n  let glow = exp(-dist * dist * (13.0 - 5.0 * u.ridgeAmt));\n  let shimmer = lqFbm(vec2<f32>(p.x * 4.0 + t * 0.22,\n                                p.y * 7.0 + offset * 5.0), 0.012).x;\n  return glow * (0.64 + 0.36 * shimmer);\n}\nfn glsAuroraFluid(p: vec2<f32>, t: f32) -> vec3<f32> {\n  let q = p * (0.82 + u.zoom * 0.58);\n  let l0 = glsAuroraLayer(q, t, -0.72);\n  let l1 = glsAuroraLayer(q, t, 0.0);\n  let l2 = glsAuroraLayer(q, t, 0.72);\n  var color = u.colorA.rgb * (0.46 + 0.18 * (q.y + 1.0));\n  color = color + u.colorB.rgb * l0 * 1.3;\n  color = color + u.colorC.rgb * l1 * 1.15;\n  color = color + u.colorD.rgb * l2 * 1.2;\n  color = color + mix(u.colorB.rgb, u.colorD.rgb, 0.5) * min(l0 * l2, l1) * 0.65;\n  let starUv = (q + vec2<f32>(1.0)) * 18.0;\n  let starCell = floor(starUv);\n  let starHash = lqHash(starCell);\n  let starPoint = exp(-dot(fract(starUv) - vec2<f32>(0.5),\n                            fract(starUv) - vec2<f32>(0.5)) * 90.0);\n  let stars = step(0.965, starHash) * starPoint\n              * (0.55 + 0.45 * sin(t * (1.0 + starHash * 2.0) + starHash * 6.28));\n  color = color + u.highlightColor.rgb * stars * (1.0 - clamp(l0 + l1 + l2, 0.0, 1.0));\n  color = color / (vec3<f32>(1.0) + color * 0.28);\n  return glsFinishPresetFluid(color, p);\n}\nfn glsRotate(p: vec2<f32>, angle: f32) -> vec2<f32> {\n  let c = cos(angle);\n  let s = sin(angle);\n  return vec2<f32>(c * p.x - s * p.y, s * p.x + c * p.y);\n}\nfn glsNeuroShape(pIn: vec2<f32>, t: f32) -> f32 {\n  var p = pIn * (0.34 + 0.08 * u.zoom);\n  var sineAccum = vec2<f32>(0.0);\n  var result = vec2<f32>(0.0);\n  var scale = 8.0;\n  for (var j: i32 = 0; j < 11; j = j + 1) {\n    p = glsRotate(p, 1.0);\n    sineAccum = glsRotate(sineAccum, 1.0);\n    let layer = p * scale + vec2<f32>(f32(j)) + sineAccum - vec2<f32>(t * 0.34);\n    sineAccum = sineAccum + sin(layer);\n    result = result + (vec2<f32>(0.5) + 0.5 * cos(layer)) / scale;\n    scale = scale * 1.16;\n  }\n  return result.x + result.y;\n}\nfn glsPlasmaFluid(p: vec2<f32>, t: f32) -> vec3<f32> {\n  let shape = glsNeuroShape(p, t);\n  let phase = shape * (10.0 + u.warp) + p.x * 1.7 - p.y * 1.3 - t * 0.52;\n  let ridgeWidth = 0.62 - 0.24 * u.ridgeAmt;\n  let primary = pow(abs(cos(phase)), max(1.3, u.sharp * ridgeWidth));\n  let secondary = pow(abs(cos(phase * 0.53 + atan2(p.y, p.x) * 2.0 + t * 0.21)),\n                      max(1.6, u.sharp * (ridgeWidth + 0.1)));\n  let filaments = max(primary, secondary * 0.64);\n  let core = pow(primary, 4.0);\n  let polarity = 0.5 + 0.5 * sin(phase * 0.37 + shape * 3.0);\n  var color = mix(u.colorA.rgb * 0.42, u.colorD.rgb * 0.48, polarity * 0.46);\n  color = mix(color, u.colorB.rgb, filaments * 0.72);\n  color = mix(color, u.colorC.rgb, core * 0.68);\n  color = color + u.highlightColor.rgb * pow(core, 3.0) * 0.16;\n  color = color / (vec3<f32>(1.0) + color * 0.34);\n  return glsFinishPresetFluid(color, p);\n}\nfn glsChromeFluid(p: vec2<f32>, t: f32) -> vec3<f32> {\n  var q = p * (1.0 + u.zoom * 0.35);\n  let amplitude = 0.028 * u.warp;\n  for (var i: i32 = 1; i <= 9; i = i + 1) {\n    let fi = f32(i);\n    q.x = q.x + amplitude / fi * cos(fi * 2.7 * q.y + t * 0.46);\n    q.y = q.y + amplitude / fi * cos(fi * 3.1 * q.x - t * 0.4);\n  }\n  let denominator = max(abs(sin(t * 0.24 - q.y - q.x)), 0.045);\n  let flare = clamp(1.0 / denominator, 0.0, 18.0);\n  let metal = smoothstep(1.15, 7.5, flare);\n  let fold = 0.5 + 0.5 * cos((q.x - q.y) * (3.2 + u.sharp * 0.28) + t * 0.32);\n  let value = clamp(metal * 0.74 + fold * 0.36, 0.0, 1.0);\n  var color = lqRamp(value, u.colorD.rgb, u.colorC.rgb, u.colorB.rgb, u.colorA.rgb);\n  color = mix(color, u.colorA.rgb, pow(metal, 5.0) * 0.62);\n  return glsFinishPresetFluid(color, p);\n}\nfn glsChromaticMetalPhase(p: vec2<f32>, t: f32) -> f32 {\n  let angle = u.metalAngle * 0.01745329252;\n  let scale = max(u.metalScale, 0.05);\n  let stretch = mix(0.48, 1.58, clamp(u.metalStretch, 0.0, 1.0));\n  var q = glsRotate(p / scale, angle);\n  q = vec2<f32>(q.x / stretch, q.y * stretch);\n  let cycle = t * 0.46 + u.metalPhase * 6.28318530718;\n  let evolution = clamp(u.metalEvolution, 0.0, 2.0);\n  q.x = q.x + sin(q.y * 1.86 - cycle) * 0.095 * evolution;\n  q.x = q.x + sin((q.x + q.y) * 1.28 + cycle * 2.0 + 1.4) * 0.045 * evolution;\n  q.y = q.y + sin(q.x * 1.52 + cycle + 0.8) * 0.07 * evolution;\n  let repeats = max(u.bandDensity, 1.0);\n  return q.x * repeats * 2.18\n       + sin(q.y * (1.3 + repeats * 0.26) - cycle) * 0.56 * evolution\n       + sin((q.x - q.y) * 1.34 + cycle * 2.0 + 1.7) * 0.27 * evolution\n       + sin((q.x * 0.72 + q.y) * 2.1 - cycle * 3.0 + 0.35) * 0.11 * evolution\n       + sin(cycle) * 0.1\n       + sin(cycle * 3.0 + 0.7) * 0.035\n       + cycle\n       + u.metalOffset * 6.28318530718;\n}\nfn glsChromaticMetalTone(phase: f32) -> f32 {\n  let wave = 0.5 + 0.5 * cos(phase);\n  let roughness = clamp(u.metalRoughness, 0.0, 1.0);\n  let depth = clamp(u.metalDepth, 0.0, 1.0);\n  let edge = 0.025 + roughness * 0.18;\n  let broadReflection = smoothstep(0.5 - edge, 0.5 + edge, wave);\n  let hardReflection = pow(wave, mix(13.0, 4.0, roughness));\n  let blackFold = pow(1.0 - wave, mix(9.0, 3.0, roughness));\n  let body = mix(wave, broadReflection, 0.2 + depth * 0.3);\n  return clamp(0.018 + body * (0.46 + depth * 0.12)\n               + hardReflection * (0.3 + depth * 0.42)\n               - blackFold * (0.07 + depth * 0.11), 0.0, 1.0);\n}\nfn glsChromaticMetalSample(p: vec2<f32>, t: f32) -> vec3<f32> {\n  let phase = glsChromaticMetalPhase(p, t);\n  let angle = u.metalAngle * 0.01745329252;\n  let brushP = glsRotate(p / max(u.metalScale, 0.05), angle);\n  let brushed = sin(brushP.y * 146.0 + sin(brushP.x * 11.0) * 0.58)\n              + 0.48 * sin(brushP.y * 317.0 - brushP.x * 5.0);\n  let brushAmount = 0.004 + clamp(u.metalRoughness, 0.0, 1.0) * 0.014;\n  let tone = clamp(glsChromaticMetalTone(phase) + brushed * brushAmount, 0.0, 1.0);\n  return lqRamp(tone, u.colorD.rgb, u.colorB.rgb, u.colorC.rgb, u.colorA.rgb);\n}\nfn glsChromaticMetalFluid(p: vec2<f32>, t: f32) -> vec3<f32> {\n  let angle = u.metalAngle * 0.01745329252;\n  let splitDirection = glsRotate(vec2<f32>(0.0, 1.0), angle);\n  let split = splitDirection * u.chromaticShift * 0.045;\n  let redSample = glsChromaticMetalSample(p + split, t);\n  let neutral = glsChromaticMetalSample(p, t);\n  let blueSample = glsChromaticMetalSample(p - split, t);\n  let optical = vec3<f32>(redSample.r, neutral.g, blueSample.b);\n  let fringe = clamp(length(optical - neutral) * 4.0, 0.0, 1.0);\n  var color = mix(neutral, optical,\n                  clamp(u.chromaticShift * (0.72 + fringe * 0.28), 0.0, 1.0));\n  let centerTone = glsChromaticMetalTone(glsChromaticMetalPhase(p, t));\n  let glint = pow(centerTone, mix(12.0, 5.0, clamp(u.metalRoughness, 0.0, 1.0)));\n  color = mix(color, u.highlightColor.rgb,\n              glint * clamp(u.metalDepth, 0.0, 1.0) * 0.06);\n  let radial2 = clamp(dot(p, p), 0.0, 1.0);\n  let normal = normalize(vec3<f32>(p, sqrt(max(1.0 - radial2, 0.0))));\n  let roughness = clamp(u.metalRoughness, 0.0, 1.0);\n  let depth = clamp(u.metalDepth, 0.0, 1.0);\n  let key = pow(max(dot(normal, normalize(vec3<f32>(-0.48, 0.62, 0.62))), 0.0),\n                mix(7.0, 3.0, roughness));\n  let fill = pow(max(dot(normal, normalize(vec3<f32>(0.7, -0.34, 0.63))), 0.0),\n                 mix(10.0, 4.0, roughness));\n  let limb = 1.0 - normal.z;\n  let fresnel = pow(limb, 3.0);\n  let rim = pow(limb, 10.0);\n  color = color * (0.86 + normal.z * 0.14);\n  color = mix(color, u.highlightColor.rgb, key * (0.05 + depth * 0.13));\n  color = mix(color, u.colorC.rgb, fill * (0.025 + depth * 0.07));\n  color = mix(color, u.colorD.rgb, fresnel * (0.12 + depth * 0.15));\n  color = mix(color, u.highlightColor.rgb, rim * (0.035 + depth * 0.055));\n  return glsFinishPresetFluid(color, p);\n}\nfn glsOpalFluid(p: vec2<f32>, t: f32) -> vec3<f32> {\n  let q = p * (0.8 + u.zoom * 0.64);\n  let complexity = 0.76 + u.warp * 0.085;\n  var d = -t * 0.42;\n  var a = 0.0;\n  for (var i: i32 = 0; i < 8; i = i + 1) {\n    let fi = f32(i);\n    a = a + cos(fi - d - a * q.x * complexity);\n    d = d + sin(q.y * fi * complexity + a);\n  }\n  d = d + t * 0.42;\n  let c1 = cos(q * vec2<f32>(d, a)) * 0.6 + vec2<f32>(0.4);\n  let c2 = cos(a + d) * 0.5 + 0.5;\n  let interference = 0.5 + 0.5 * cos(vec3<f32>(c1.x, c1.y, c2)\n                         * cos(vec3<f32>(d, a, 2.5)) * 0.5 + vec3<f32>(0.5));\n  let tone = fract(interference.r * 0.37 + interference.g * 0.51\n                   + interference.b * 0.73 + c1.x * 0.22 - c1.y * 0.15);\n  var color = lqRamp(tone, u.colorB.rgb, u.colorC.rgb, u.colorD.rgb, u.colorA.rgb);\n  color = mix(color, u.colorA.rgb, 0.16 + 0.1 * interference.b);\n  color = color / (vec3<f32>(1.0) + color * 0.16);\n  return glsFinishPresetFluid(color, p);\n}\nfn glsFrostFluid(p: vec2<f32>, t: f32) -> vec3<f32> {\n  var q = p * (0.66 + u.zoom * 0.92);\n  q.y = q.y + t * 0.055;\n  let blur = 0.011 + 0.006 * u.zoom;\n  let warpField = vec2<f32>(\n    lqFbm(q * 1.14 + vec2<f32>(t * 0.055, 0.0), blur).x,\n    lqFbm(q * 1.14 + vec2<f32>(6.8, -t * 0.048), blur).x\n  );\n  let warped = q + (warpField - vec2<f32>(0.5)) * (0.28 + u.warp * 0.17);\n  let body = lqFbm(warped * 1.48 + vec2<f32>(t * 0.032, -t * 0.02), blur * 1.48);\n  let veins = lqRidgeS(\n    lqFbm(warped * 2.36 + vec2<f32>(3.1, -t * 0.024), blur * 2.36),\n    u.sharp\n  );\n  let value = mix(lqStepS(body, 0.1, 0.9),\n                  clamp(veins * 0.8 + body.x * 0.46, 0.0, 1.0),\n                  u.ridgeAmt);\n  var color = lqRamp(value, u.colorA.rgb, u.colorB.rgb, u.colorC.rgb, u.colorD.rgb);\n  color = mix(color, u.colorA.rgb, 0.08 * smoothstep(0.62, 0.92, body.x));\n  return glsFinishPresetFluid(color, p);\n}\nfn glsVoiceWaveFluid(p: vec2<f32>, t: f32) -> vec3<f32> {\n  let scale = 0.76 + u.zoom * 0.34;\n  let q = p / scale;\n  let rimEnvelope = pow(max(1.0 - q.x * q.x, 0.0), 0.72);\n  let drift = t * 0.82;\n  let amplitude = 0.2 + u.warp * 0.018;\n  let mainY = rimEnvelope * (amplitude * sin(q.x * 1.48 + drift)\n              + 0.055 * sin(q.x * 3.2 - drift * 0.43 + 1.1));\n  let distance = q.y - mainY;\n  let width = 0.11 + (1.0 - u.ridgeAmt) * 0.075;\n  let membrane = exp(-distance * distance / max(width * width, 0.001)) * rimEnvelope;\n  let upperVeil = exp(-(distance - 0.105) * (distance - 0.105)\n                      / max(width * width * 2.4, 0.001)) * rimEnvelope;\n  let lowerVeil = exp(-(distance + 0.115) * (distance + 0.115)\n                      / max(width * width * 2.8, 0.001)) * rimEnvelope;\n  let crest = exp(-distance * distance / 0.0026) * rimEnvelope;\n  let depth = sqrt(max(1.0 - clamp(dot(p, p), 0.0, 1.0), 0.0));\n  var color = mix(u.colorA.rgb * 0.7, u.colorD.rgb * 0.34,\n                  smoothstep(-0.82, 0.82, q.y));\n  color = mix(color, u.colorB.rgb, upperVeil * 0.7);\n  color = mix(color, u.colorC.rgb, lowerVeil * 0.62);\n  color = color + mix(u.colorB.rgb, u.colorC.rgb, 0.46) * membrane * 0.34;\n  color = color + u.highlightColor.rgb * crest * 0.14;\n  color = color * (0.58 + 0.42 * depth);\n  return glsFinishPresetFluid(color, p);\n}\nfn glsBlueDropFluid(p: vec2<f32>, t: f32) -> vec3<f32> {\n  let depth = sqrt(max(1.0 - clamp(dot(p, p), 0.0, 1.0), 0.0));\n  var q = p * mix(0.72, 1.0, depth * 0.62 + 0.38);\n  q = glsRotate(q, -0.24 + 0.06 * sin(t * 0.17));\n  let scale = 1.0 + u.zoom * 1.12;\n  let blur = 0.012 + 0.006 * u.zoom;\n  let driftA = lqFbm(q * 1.28 + vec2<f32>(t * 0.095, -t * 0.034), blur * 1.28);\n  let driftB = lqFbm(glsRotate(q, 1.08) * 1.62\n                     + vec2<f32>(-t * 0.042, t * 0.078), blur * 1.62);\n  var flowed = q + vec2<f32>(driftA.x - 0.5, driftB.x - 0.5)\n                 * (0.24 + u.warp * 0.1);\n  flowed.x = flowed.x + sin(flowed.y * 2.15 + t * 0.24) * (0.035 + u.warp * 0.012);\n  flowed.y = flowed.y + sin(flowed.x * 1.38 - t * 0.18) * (0.045 + u.warp * 0.01);\n  let body = lqFbm(flowed * scale + vec2<f32>(t * 0.025, -t * 0.018), blur * scale);\n  let marble = lqRidgeS(lqFbm(flowed * (1.72 + u.zoom * 0.9)\n                              + vec2<f32>(2.7, -t * 0.035),\n                              blur * (1.72 + u.zoom * 0.9)),\n                            0.8 + u.sharp * 0.46);\n  let value = clamp(mix(body.x, body.x * 0.62 + marble * 0.58, u.ridgeAmt), 0.0, 1.0);\n  var color = lqRamp(value, u.colorA.rgb, u.colorB.rgb, u.colorC.rgb, u.colorD.rgb);\n  let light = pow(max(dot(normalize(vec3<f32>(p, depth)),\n                          normalize(vec3<f32>(-0.48, 0.62, 0.92))), 0.0), 3.2);\n  color = mix(color, u.highlightColor.rgb, light * (0.035 + 0.05 * u.shade));\n  color = color * (0.74 + 0.26 * depth);\n  return glsFinishPresetFluid(color, p);\n}\nfn glsVioletEmberFluid(p: vec2<f32>, t: f32) -> vec3<f32> {\n  let scale = 1.08 + u.zoom * 1.18;\n  let blur = 0.011 + 0.005 * u.zoom;\n  let radius = length(p);\n  let twist = t * 0.055 + radius * (0.72 + u.warp * 0.11)\n              + 0.08 * sin(t * 0.31 + radius * 4.0);\n  let q = glsRotate(p * scale, twist);\n  let low = lqFbm(q * 1.18 + vec2<f32>(t * 0.068, -t * 0.105), blur * 1.18);\n  let cross = lqFbm(glsRotate(q, -1.12) * 1.52\n                    + vec2<f32>(-t * 0.094, t * 0.042)\n                    + vec2<f32>(low.x * 1.35, -low.x * 0.72), blur * 1.52);\n  let warped = q + vec2<f32>(low.x - 0.5, cross.x - 0.5)\n                   * (0.3 + u.warp * 0.12);\n  let melt = lqFbm(warped * 1.34\n                   + vec2<f32>(cross.x * 1.48, low.x * 1.12), blur * 1.34);\n  let veins = lqRidgeS(lqFbm(warped * (2.05 + u.zoom * 0.72)\n                             + vec2<f32>(-2.1, t * 0.052),\n                             blur * (2.05 + u.zoom * 0.72)),\n                           0.82 + u.sharp * 0.58);\n  let heat = smoothstep(0.18, 0.92,\n                        melt.x * (0.72 - u.ridgeAmt * 0.16)\n                        + veins * (0.32 + u.ridgeAmt * 0.5));\n  var color = lqRamp(heat, u.colorA.rgb, u.colorB.rgb, u.colorC.rgb, u.colorD.rgb);\n  let pulse = 0.94 + 0.06 * sin(t * 0.44 + melt.x * 5.0);\n  color = color * pulse;\n  color = mix(color, u.highlightColor.rgb, pow(veins, 4.0) * 0.045);\n  return glsFinishPresetFluid(color, p);\n}\nfn glsRefractiveBlobFluid(p: vec2<f32>, t: f32) -> vec3<f32> {\n  let radial2 = clamp(dot(p, p), 0.0, 1.0);\n  let depth = sqrt(max(1.0 - radial2, 0.0));\n  let scale = 0.82 + u.zoom * 1.08;\n  let blur = 0.012 + 0.005 * u.zoom;\n  var q = glsRotate(p * scale, 0.08 * sin(t * 0.17));\n  let driftA = lqFbm(q * 1.16 + vec2<f32>(t * 0.052, -t * 0.078), blur * 1.16);\n  let driftB = lqFbm(glsRotate(q, 1.21) * 1.34\n                     + vec2<f32>(-t * 0.064, t * 0.041), blur * 1.34);\n  q = q + vec2<f32>(driftA.x - 0.5, driftB.x - 0.5)\n          * (0.34 + u.warp * 0.105);\n  let body = lqFbm(q * 1.42 + vec2<f32>(driftB.x * 0.82, driftA.x * 0.66),\n                   blur * 1.42);\n  let ribbonPhase = q.y * (2.2 + u.warp * 0.11)\n                  + sin(q.x * 1.72 - t * 0.19) * 0.92\n                  + sin((q.x + q.y) * 1.08 + t * 0.13) * 0.46;\n  let ribbon = pow(clamp(1.0 - abs(sin(ribbonPhase)), 0.0, 1.0),\n                   0.82 + u.sharp * 0.23);\n  let fold = lqRidgeS(lqFbm(q * 2.05 + vec2<f32>(2.8, -t * 0.037),\n                            blur * 2.05), 0.9 + u.sharp * 0.32);\n  let value = clamp(body.x * 0.5 + driftA.x * 0.16\n                    + ribbon * (0.2 + u.ridgeAmt * 0.2)\n                    + fold * u.ridgeAmt * 0.18, 0.0, 1.0);\n  var color = lqRamp(value, u.colorA.rgb, u.colorB.rgb, u.colorC.rgb, u.colorD.rgb);\n  let caustic = pow(ribbon, 3.1) * (0.24 + 0.28 * u.ridgeAmt)\n               + pow(fold, 4.2) * 0.08;\n  color = mix(color, u.colorD.rgb, clamp(caustic, 0.0, 0.52));\n  color = color * (0.7 + depth * 0.3);\n  let key = pow(max(dot(normalize(vec3<f32>(p, depth)),\n                        normalize(vec3<f32>(-0.42, 0.58, 0.9))), 0.0), 4.0);\n  color = mix(color, u.highlightColor.rgb, key * 0.055);\n  return glsFinishPresetFluid(color, p);\n}\nfn glsParticleRibbonFluid(p: vec2<f32>, t: f32) -> vec3<f32> {\n  return vec3<f32>(0.0);\n}\nfn glsPresetFluid(p: vec2<f32>, style: i32, t: f32) -> vec3<f32> {\n  if (style == 9) { return glsSiriFluid(p, t); }\n  if (style == 10) { return glsAuroraFluid(p, t); }\n  if (style == 11) { return glsPlasmaFluid(p, t); }\n  if (style == 12) { return glsChromeFluid(p, t); }\n  if (style == 13) { return glsOpalFluid(p, t); }\n  if (style == 14) { return glsSpectrumFluid(p, t); }\n  if (style == 15) { return glsFrostFluid(p, t); }\n  if (style == 19) { return glsVoiceWaveFluid(p, t); }\n  if (style == 20) { return glsBlueDropFluid(p, t); }\n  if (style == 21) { return glsVioletEmberFluid(p, t); }\n  if (style == 22) { return glsChromaticMetalFluid(p, t); }\n  if (style == 23) { return glsRefractiveBlobFluid(p, t); }\n  if (style == 24) { return glsParticleRibbonFluid(p, t); }\n  return glsFrostFluid(p, t);\n}\nfn glsFluid(fu: vec2<f32>, md: i32, t: f32) -> vec3<f32> {\n  let df = length(fu);\n  let cA = u.colorA.rgb;\n  let cB = u.colorB.rgb;\n  let cC = u.colorC.rgb;\n  let cD = u.colorD.rgb;\n  let blurSigma = select(GL_BSIG_CLEAR, GL_BSIG_GLASS, u.glassEnabled > 0.5);\n  let sp = blurSigma * u.zoom;\n  let sw = sp * 1.1 * GL_KWA;\n  var fcol: vec3<f32>;\n  if (md < 0) {\n    var pp = fu * u.zoom;\n    pp.y = pp.y + t * 0.05;\n    let w = vec2<f32>(lqFbm(pp * 1.1 + vec2<f32>(0.0, t * 0.09), sw).x,\n                      lqFbm(pp * 1.1 + vec2<f32>(7.7, -t * 0.07), sw).x);\n    let q = pp + u.warp * (w - vec2<f32>(0.5));\n    let body  = lqFbm(q * 1.5 + vec2<f32>(t * 0.04, 0.0), sp * 1.5);\n    let veins = lqRidgeS(lqFbm(q * 2.2 + vec2<f32>(3.1), sp * 2.2), u.sharp);\n    let v = mix(lqStepS(body, 0.12, 0.88),\n                clamp(veins * 0.85 + 0.45 * body.x, 0.0, 1.0), u.ridgeAmt);\n    fcol = lqRamp(v, cA, cB, cC, cD);\n  } else {\n    let pp = fu * u.zoom;\n    let w = vec2<f32>(lqFbm(pp * 1.1 + vec2<f32>(0.0, t * 0.09), sw).x,\n                      lqFbm(pp * 1.1 + vec2<f32>(7.7, -t * 0.07), sw).x);\n    let q = pp + u.warp * (w - vec2<f32>(0.5));\n    if (md == 0) {\n      let n0 = lqFbm(q * 2.2, sp * 2.2);\n      let damp = exp(-18.0 * n0.y * n0.y - 24.5 * sp * sp);\n      var v = 0.5 + 0.5 * damp * sin(q.x * 7.0 + n0.x * 6.0 + t * 0.35);\n      v = mix(v, lqFbm(q * 1.4 + vec2<f32>(t * 0.03), sp * 1.4).x, 0.25);\n      fcol = lqRamp(v, cA, cB, cC, cD);\n    } else if (md == 1) {\n      let v = lqRidgeS(lqFbm(q * 1.4 + vec2<f32>(t * 0.06, 0.0), sp * 1.4), u.sharp)\n            * lqRidgeS(lqFbm(q * 1.7 - vec2<f32>(0.0, t * 0.05), sp * 1.7), u.sharp);\n      fcol = lqRamp(pow(v, 0.7), cA, cB, cC, cD);\n    } else if (md == 6) {\n      let v = lqFbm(q * 1.3 + vec2<f32>(1.5 * lqFbm(q * 2.6 + vec2<f32>(t * 0.025), sp * 2.6).x), sp * 1.3);\n      let edge = lqRidgeS(lqFbm(q * 2.1 + vec2<f32>(7.0), sp * 2.1), 1.3);\n      fcol = lqRamp(lqStepS(v, 0.1, 0.9), cA, cB, cC, cD);\n      fcol = fcol * (1.0 - 0.18 * edge);\n    } else {\n      let q2 = q + vec2<f32>(0.0, -t * 0.14);\n      let v = lqFbm(q2 * 1.6 + vec2<f32>(2.2 * lqFbm(q2 * 2.4 + vec2<f32>(0.0, -t * 0.05), sp * 2.4).x), sp * 1.6);\n      fcol = lqRamp(lqPowS(v, 1.5), cA, cB, cC, cD);\n    }\n  }\n  fcol = mix(fcol, u.highlightColor.rgb,\n             u.shade * 0.3 * smoothstep(0.25, 1.25, dot(fu, vec2<f32>(-0.32, 0.78))));\n  fcol = fcol * (1.0 - u.shade * 0.42 * smoothstep(-0.05, 1.25, dot(fu, vec2<f32>(0.45, -0.62))));\n  fcol = fcol * (1.0 - u.shade * 0.3 * smoothstep(0.72, 1.0, df));\n  return clamp(fcol, vec3<f32>(0.0), vec3<f32>(1.0));\n}\nfn glsOver(dst: vec3<f32>, src: vec3<f32>, a: f32) -> vec3<f32> {\n  let k = clamp(a, 0.0, 1.0);\n  return src * k + dst * (1.0 - k);\n}\nfn glsRefractionProfile(t: f32) -> f32 {\n  let depth = clamp(t, 0.0, 1.0);\n  let circular = sqrt(max(1.0 - (1.0 - depth) * (1.0 - depth), 0.0));\n  return 1.0 - circular;\n}\nfn glsHighlightLobe(normal: vec2<f32>, direction: vec2<f32>, cut: f32,\n                     power: f32) -> f32 {\n  let angular = clamp((dot(normal, direction) - cut) / max(1.0 - cut, 0.001),\n                      0.0, 1.0);\n  return pow(angular, power);\n}\nfn glsContourWave(angle: f32, t: f32) -> vec2<f32> {\n  let style = i32(u.style + 0.5);\n  if (style == 19) {\n    let wave = sin(angle * 2.0 + t * 0.27) * 0.72\n               + sin(angle * 4.0 - t * 0.16 + 2.1) * 0.28;\n    let slope = cos(angle * 2.0 + t * 0.27) * 1.44\n                + cos(angle * 4.0 - t * 0.16 + 2.1) * 1.12;\n    return vec2<f32>(wave, slope);\n  }\n  let wave = sin(angle * 3.0 + t * 0.62) * 0.52\n             + sin(angle * 5.0 - t * 0.41 + 1.7) * 0.31\n             + sin(angle * 2.0 + t * 0.23 + 3.1) * 0.17;\n  let slope = cos(angle * 3.0 + t * 0.62) * 1.56\n              + cos(angle * 5.0 - t * 0.41 + 1.7) * 1.55\n              + cos(angle * 2.0 + t * 0.23 + 3.1) * 0.34;\n  return vec2<f32>(wave, slope);\n}\nfn glsContourStrength() -> f32 {\n  if (u.style >= 18.5) { return 0.11; }\n  return select(0.09, 0.16, u.style >= 15.5);\n}\nfn glsContourScale(uv: vec2<f32>, t: f32, amount: f32) -> f32 {\n  if (amount <= 0.0) { return 1.0; }\n  let contour = glsContourWave(atan2(uv.y, uv.x), t);\n  return 1.0 + clamp(amount, 0.0, 1.0) * glsContourStrength() * contour.x;\n}\nfn glsContourNormal(uv: vec2<f32>, rad: f32, t: f32, amount: f32) -> vec2<f32> {\n  let distance = length(uv);\n  if (distance <= 0.0001) { return vec2<f32>(0.0); }\n  let radial = uv / distance;\n  let contour = glsContourWave(atan2(uv.y, uv.x), t);\n  let slope = clamp(amount, 0.0, 1.0) * glsContourStrength() * contour.y;\n  let tangent = vec2<f32>(-radial.y, radial.x);\n  return normalize(radial - tangent * (rad * slope / distance));\n}\nfn glsRefractionNormal(base: vec2<f32>, p: vec2<f32>, t: f32,\n                       style: i32) -> vec2<f32> {\n  if (style != 23) { return base; }\n  let tangent = vec2<f32>(-base.y, base.x);\n  let a = lqFbm(p * 2.15 + vec2<f32>(t * 0.061, -t * 0.043), 0.018).x;\n  let b = lqFbm(glsRotate(p, 1.37) * 2.55\n                  + vec2<f32>(-t * 0.037, t * 0.052), 0.021).x;\n  let wave = (a - b) * 0.76 + sin(atan2(p.y, p.x) * 3.0 + t * 0.21) * 0.08;\n  return normalize(base + tangent * wave);\n}\nfn orbGlassLiquidAnim(uv01: vec2<f32>) -> vec4<f32> {\n  let fc = vec2<f32>(uv01.x, 1.0 - uv01.y) * u.size;\n  let uv = (2.0 * fc - u.size) / max(min(u.size.x, u.size.y), 1.0);\n  let rad = max(u.radius, 0.05);\n  let t = u.time * u.speed;\n  let s = i32(u.style + 0.5);\n  let emissionOnly = u.glassEnabled <= 0.5 && (s == 9 || s == 14 || s == 24);\n  let contourRad = rad * glsContourScale(uv, t, u.contourDeform);\n  if (length(uv) > contourRad * (1.01 + mfEdgeD(u.edgeSoftness))) {\n    let halo = clamp(mfEdgeGlow(vec3<f32>(0.0), uv, vec2<f32>(0.0), contourRad,\n                                u.edgeSoftness, u.edgeGlow, u.glowColor.rgb),\n                     vec3<f32>(0.0), vec3<f32>(1.0));\n    let haloAlpha = max(halo.r, max(halo.g, halo.b));\n    return vec4<f32>(halo, haloAlpha);\n  }\n  let p   = uv / contourRad;\n  let pd  = length(p);\n  let fu = p / GL_FU;\n  var md: i32 = -1;\n  if (s == 1) { md = 1; }\n  else if (s == 3 || s == 8) { md = 7; }\n  else if (s == 5) { md = 6; }\n  else if (s == 7) { md = 0; }\n  let clearFa = 1.0 - smoothstep(GL_CLEAR_EA, GL_CLEAR_EB, pd);\n  let contourNormal = glsContourNormal(uv, rad, t, u.contourDeform);\n  let normal = glsRefractionNormal(contourNormal, p, t, s);\n  let edgeDepth = max(1.0 - pd, 0.0);\n  let refractionWidth = 0.015 + 0.95 * clamp(u.shellMidAlpha, 0.0, 1.0);\n  let refractionT = edgeDepth / max(refractionWidth, 0.001);\n  let refractionProfile = pow(glsRefractionProfile(refractionT), 0.68);\n  let refractionAmount = 1.6 * clamp(u.glassOpacity, 0.0, 1.0)\n                         * refractionProfile;\n  let refractedP = p - normal * refractionAmount;\n  var fcol = vec3<f32>(0.0);\n  if (clearFa > 0.0) {\n    if (s >= 9) {\n      if (u.glassEnabled > 0.5) {\n        let channelSplit = 0.14 * clamp(u.gloss, 0.0, 2.0)\n                           * clamp(u.glassOpacity, 0.0, 1.0)\n                           * refractionProfile;\n        let redSample = glsPresetFluid(refractedP - normal * channelSplit, s, t);\n        let greenSample = glsPresetFluid(refractedP, s, t);\n        let blueSample = glsPresetFluid(refractedP + normal * channelSplit, s, t);\n        fcol = vec3<f32>(redSample.r, greenSample.g, blueSample.b);\n      }\n      else { fcol = glsPresetFluid(p, s, t); }\n    }\n    else { fcol = glsFluid(fu, md, t); }\n  }\n  let lum = dot(fcol, vec3<f32>(0.213, 0.715, 0.072));\n  let clearSat = clamp(vec3<f32>(lum) + (fcol - vec3<f32>(lum)) * 1.22,\n                       vec3<f32>(0.0), vec3<f32>(1.0));\n  let particleGlassOverlay = s == 24;\n  var col = select(\n    glsOver(u.canvasColor.rgb, clearSat, 0.99 * clearFa),\n    vec3<f32>(0.0),\n    particleGlassOverlay,\n  );\n  if (emissionOnly) {\n    let signal = max(clearSat.r, max(clearSat.g, clearSat.b));\n    let emissionCoverage = smoothstep(0.025, 0.16, signal);\n    col = clearSat * emissionCoverage;\n  }\n  if (u.glassEnabled > 0.5) {\n    let surfaceWidth = select(\n      0.026 + 0.055 * clamp(u.shellEdgeAlpha, 0.0, 1.0),\n      0.09 + 0.12 * clamp(u.shellEdgeAlpha, 0.0, 1.0),\n      particleGlassOverlay,\n    );\n    let surfaceBand = (1.0 - smoothstep(0.0, surfaceWidth, edgeDepth)) * clearFa;\n    let opticalRim = pow(surfaceBand, select(1.8, 1.3, particleGlassOverlay));\n    let innerRimAlpha = select(\n      opticalRim * u.glassOpacity * 0.45,\n      opticalRim * u.glassOpacity * 0.14,\n      particleGlassOverlay,\n    );\n    col = glsOver(col, u.shellInner.rgb, innerRimAlpha);\n    let coolDirection = normalize(vec2<f32>(0.84, 0.54));\n    let warmDirection = normalize(vec2<f32>(-0.62, -0.78));\n    let coolSplit = glsHighlightLobe(normal, coolDirection, -0.32, 1.8);\n    let warmSplit = glsHighlightLobe(normal, warmDirection, -0.28, 2.0);\n    let dispersion = opticalRim * clamp(u.gloss, 0.0, 2.0)\n                     * (0.8 + 0.8 * u.shellEdgeAlpha);\n    col = glsOver(col, u.shellMid.rgb, dispersion * coolSplit);\n    col = glsOver(col, u.shellEdge.rgb, dispersion * warmSplit);\n    let edgeShadow = opticalRim * (0.015 + 0.15 * u.shellEdgeAlpha)\n                     * (0.15 + 0.85 * max(dot(normal, vec2<f32>(0.45, -0.89)), 0.0));\n    col = col * (1.0 - edgeShadow);\n    let keyDirection = normalize(vec2<f32>(-0.68, 0.73));\n    let fillDirection = normalize(vec2<f32>(0.74, -0.67));\n    let key = opticalRim * glsHighlightLobe(normal, keyDirection, 0.2, 2.8)\n              * clamp(u.sheen, 0.0, 2.0) * 1.4;\n    let fill = opticalRim * glsHighlightLobe(normal, fillDirection, 0.4, 3.6)\n               * clamp(u.sheen, 0.0, 2.0) * 1.0;\n    col = glsOver(col, u.sheenColor.rgb, key);\n    col = glsOver(col, u.specColor.rgb, fill);\n  }\n  let ballA = 1.0 - smoothstep(0.99 - mfEdgeD(u.edgeSoftness), 1.01 + mfEdgeD(u.edgeSoftness), pd);\n  col = clamp(col * max(u.exposure, 0.0), vec3<f32>(0.0), vec3<f32>(1.0)) * ballA;\n  let edged = mfEdgeGlow(col, uv, vec2<f32>(0.0), contourRad,\n                         u.edgeSoftness, u.edgeGlow, u.glowColor.rgb);\n  let finalColor = clamp(edged, vec3<f32>(0.0), vec3<f32>(1.0));\n  let emissionAlpha = max(finalColor.r, max(finalColor.g, finalColor.b));\n  let sphereAlpha = clamp(max(ballA, emissionAlpha), 0.0, 1.0);\n  let finalAlpha = select(\n    sphereAlpha,\n    emissionAlpha,\n    emissionOnly || particleGlassOverlay,\n  );\n  return vec4<f32>(finalColor, finalAlpha);\n}\nstruct VOut {\n  @builtin(position) pos: vec4<f32>,\n  @location(0) uv: vec2<f32>,\n};\n@vertex\nfn vs_main(@builtin(vertex_index) i: u32) -> VOut {\n  var p = array<vec2<f32>, 3>(\n    vec2<f32>(-1.0, -1.0),\n    vec2<f32>( 3.0, -1.0),\n    vec2<f32>(-1.0,  3.0),\n  );\n  var out: VOut;\n  out.pos = vec4<f32>(p[i], 0.0, 1.0);\n  let uv01 = (p[i] + vec2<f32>(1.0)) * 0.5;\n  out.uv = vec2<f32>(uv01.x, 1.0 - uv01.y);\n  return out;\n}\n@fragment\nfn fs_main(in: VOut) -> @location(0) vec4<f32> {\n  let c = orbGlassLiquidAnim(in.uv);\n  let fc = vec2<f32>(in.uv.x, 1.0 - in.uv.y) * u.size;\n  let uv = (2.0 * fc - u.size) / max(min(u.size.x, u.size.y), 1.0);\n  let rad = max(u.radius, 0.05);\n  let t = u.time * u.speed;\n  let contourRad = rad * glsContourScale(uv, t, u.contourDeform);\n  let q = (2.0 * fc - u.size) / u.size;\n  let fitEnd = 1.0;\n  let fitFeather = 2.0 / max(min(u.size.x, u.size.y), 1.0);\n  let fitStart = min(mix(contourRad, fitEnd, 0.5), fitEnd - fitFeather);\n  let fit = 1.0 - smoothstep(fitStart, fitEnd, max(abs(q.x), abs(q.y)));\n  return vec4<f32>(c.rgb * fit, c.a * fit);\n}\nconst PR_U_SEGMENTS: u32 = 384u;\nconst PR_V_SEGMENTS: u32 = 96u;\nconst PR_PARTICLES_PER_LAYER: u32 = PR_U_SEGMENTS * PR_V_SEGMENTS;\nstruct RibbonOut {\n  @builtin(position) pos: vec4<f32>,\n  @location(0) local: vec2<f32>,\n  @location(1) color: vec3<f32>,\n  @location(2) opacity: f32,\n};\nfn prHash(value: f32) -> f32 {\n  return fract(sin(value * 12.9898 + 78.233) * 43758.5453);\n}\nfn prRotateX(p: vec3<f32>, angle: f32) -> vec3<f32> {\n  let c = cos(angle);\n  let s = sin(angle);\n  return vec3<f32>(p.x, c * p.y - s * p.z, s * p.y + c * p.z);\n}\nfn prRotateY(p: vec3<f32>, angle: f32) -> vec3<f32> {\n  let c = cos(angle);\n  let s = sin(angle);\n  return vec3<f32>(c * p.x + s * p.z, p.y, -s * p.x + c * p.z);\n}\nfn prCurve(theta: f32, layer: f32, phase: f32) -> vec3<f32> {\n  let local = theta + layer * 0.11;\n  let foldPhase = 2.0 * local + phase * (0.72 + layer * 0.025);\n  let fold = clamp(u.ribbonFold, 0.0, 1.2);\n  let radial = 0.4 + (0.085 + fold * 0.04) * cos(foldPhase);\n  let orbit = local + phase * 0.13\n              + sin(local - phase * 0.22 + layer) * fold * 0.13;\n  let vertical = (0.235 + fold * 0.085) * sin(foldPhase)\n                 + 0.055 * sin(local * 3.0 - phase * 0.46 + layer * 0.7);\n  return vec3<f32>(radial * cos(orbit), vertical, radial * sin(orbit));\n}\nfn prPalette(valueIn: f32) -> vec3<f32> {\n  let value = fract(valueIn) * 4.0;\n  if (value < 1.0) { return mix(u.colorA.rgb, u.colorB.rgb, value); }\n  if (value < 2.0) { return mix(u.colorB.rgb, u.colorC.rgb, value - 1.0); }\n  if (value < 3.0) { return mix(u.colorC.rgb, u.colorD.rgb, value - 2.0); }\n  return mix(u.colorD.rgb, u.colorA.rgb, value - 3.0);\n}\n@vertex\nfn ribbon_vs_main(\n  @builtin(vertex_index) vertexIndex: u32,\n  @builtin(instance_index) instanceIndex: u32,\n) -> RibbonOut {\n  var corners = array<vec2<f32>, 6>(\n    vec2<f32>(-1.0, -1.0), vec2<f32>(1.0, -1.0), vec2<f32>(-1.0, 1.0),\n    vec2<f32>(-1.0, 1.0), vec2<f32>(1.0, -1.0), vec2<f32>(1.0, 1.0),\n  );\n  let layerIndex = instanceIndex / PR_PARTICLES_PER_LAYER;\n  let particleIndex = instanceIndex % PR_PARTICLES_PER_LAYER;\n  let uIndex = particleIndex / PR_V_SEGMENTS;\n  let vIndex = particleIndex % PR_V_SEGMENTS;\n  let layer = f32(layerIndex);\n  let random = prHash(f32(instanceIndex));\n  let activeLayer = layer < floor(clamp(u.ribbonCount, 2.0, 6.0) + 0.5);\n  let uCoord = (f32(uIndex) + prHash(f32(instanceIndex) + 11.0) * 0.56)\n               / f32(PR_U_SEGMENTS);\n  let vCoord = (f32(vIndex) + prHash(f32(instanceIndex) + 29.0) * 0.46)\n               / f32(PR_V_SEGMENTS);\n  let strip = vCoord * 2.0 - 1.0;\n  let t = u.time * u.speed;\n  let phase = t * 0.48;\n  let arc = fract(uCoord + layer * 0.211 - phase * 0.019);\n  let arcLength = 0.76 + 0.055 * sin(t * 0.23 + layer * 1.71);\n  let arcPosition = arc / arcLength;\n  let arcEnvelope = smoothstep(0.0, 0.075, arcPosition)\n                    * (1.0 - smoothstep(0.88, 1.0, arcPosition));\n  let particleVisible = activeLayer\n                        && arc <= arcLength\n                        && random <= clamp(u.particleDensity, 0.2, 1.0);\n  let theta = uCoord * 6.28318530718;\n  let center = prCurve(theta, layer, phase);\n  let ahead = prCurve(theta + 0.006, layer, phase);\n  let tangent = normalize(ahead - center);\n  let radial = normalize(center + vec3<f32>(0.001, 0.013, 0.007));\n  let side = normalize(cross(tangent, radial));\n  let surfaceNormal = normalize(cross(side, tangent));\n  let twist = theta * (0.72 + u.ribbonTwist * 0.58)\n              + phase * 0.74 + layer * 1.17;\n  let ribbonDirection = normalize(side * cos(twist) + surfaceNormal * sin(twist));\n  let widthEnvelope = (0.72 + 0.28 * pow(sin(theta * 1.5 + phase + layer), 2.0))\n                      * mix(0.42, 1.0, sqrt(max(arcEnvelope, 0.0)));\n  var position = center + ribbonDirection * strip * u.ribbonWidth * 0.5 * widthEnvelope;\n  let pulse = sin(t * 0.73 + layer * 1.71)\n              + 0.44 * sin(t * 1.17 + layer * 0.83 + 1.2);\n  position *= 1.0 + u.ribbonBreath * pulse * 0.16;\n  let layerCenter = layer\n                    - (floor(clamp(u.ribbonCount, 2.0, 6.0) + 0.5) - 1.0) * 0.5;\n  position = prRotateY(\n    position,\n    layerCenter * 0.24 + sin(t * 0.19 + layer * 1.3) * 0.055,\n  );\n  position = prRotateX(\n    position,\n    layerCenter * 0.14 + cos(t * 0.17 + layer * 0.9) * 0.04,\n  );\n  position = prRotateY(position, t * 0.105 + sin(t * 0.21) * 0.11);\n  position = prRotateX(position, -0.2 + sin(t * 0.16 + layer * 0.1) * 0.16);\n  let minSize = max(min(u.size.x, u.size.y), 1.0);\n  let depthScale = 0.88 + position.z * 0.16;\n  let orbPosition = position.xy * u.radius * 1.45 * depthScale;\n  let clip = vec2<f32>(\n    orbPosition.x * minSize / max(u.size.x, 1.0),\n    orbPosition.y * minSize / max(u.size.y, 1.0),\n  );\n  let canvasParticleScale = clamp(minSize / 640.0, 0.22, 1.0);\n  let pointPixels = max(0.6, u.particleSize)\n                    * (1.5 + u.particleBloom * 2.5)\n                    * (0.92 + position.z * 0.18)\n                    * canvasParticleScale;\n  let corner = corners[vertexIndex];\n  let pointOffset = corner * pointPixels * 2.0 / max(u.size, vec2<f32>(1.0));\n  let colorPhase = uCoord * 0.32 + layer * 0.19 + phase * 0.025\n                   + position.z * 0.08;\n  let stripEdge = smoothstep(0.58, 1.0, abs(strip));\n  let front = clamp(0.78 + position.z * 0.54, 0.5, 1.24);\n  let baseOpacity = mix(0.025, 0.009, clamp(u.shade / 1.5, 0.0, 1.0));\n  var out: RibbonOut;\n  out.pos = select(\n    vec4<f32>(2.0, 2.0, 1.0, 1.0),\n    vec4<f32>(clip + pointOffset, clamp(0.5 - position.z * 0.12, 0.05, 0.95), 1.0),\n    particleVisible,\n  );\n  out.local = corner;\n  out.color = pow(\n    mix(prPalette(colorPhase), u.highlightColor.rgb, stripEdge * 0.56),\n    vec3<f32>(0.72),\n  ) * front;\n  out.opacity = select(\n    0.0,\n    baseOpacity\n      * (0.72 + stripEdge * 1.28)\n      * arcEnvelope\n      * pow(canvasParticleScale, 1.35),\n    particleVisible,\n  );\n  return out;\n}\n@fragment\nfn ribbon_fs_main(in: RibbonOut) -> @location(0) vec4<f32> {\n  let distanceSquared = dot(in.local, in.local);\n  if (distanceSquared > 1.0) { discard; }\n  let core = exp(-distanceSquared * 4.8);\n  let halo = exp(-distanceSquared * 1.35);\n  let bloom = clamp(u.particleBloom, 0.0, 2.0);\n  let intensity = in.opacity * (core * 1.9 + halo * bloom * 0.72)\n                  * max(u.exposure, 0.0);\n  let glowMix = clamp((halo - core * 0.45) * (0.18 + u.edgeGlow * 0.5), 0.0, 0.7);\n  let color = mix(in.color, u.glowColor.rgb, glowMix);\n  let alpha = clamp(intensity, 0.0, 1.0);\n  return vec4<f32>(color * alpha, alpha);\n}\n@group(0) @binding(1) var ribbonTexture: texture_2d<f32>;\n@group(0) @binding(2) var ribbonSampler: sampler;\nfn prTextureUvFromOrb(p: vec2<f32>, contourRad: f32) -> vec2<f32> {\n  let minSize = max(min(u.size.x, u.size.y), 1.0);\n  let fc = (p * contourRad * minSize + u.size) * 0.5;\n  return clamp(\n    vec2<f32>(fc.x / max(u.size.x, 1.0), 1.0 - fc.y / max(u.size.y, 1.0)),\n    vec2<f32>(0.0),\n    vec2<f32>(1.0),\n  );\n}\nfn prSampleRibbon(p: vec2<f32>, contourRad: f32) -> vec4<f32> {\n  return textureSampleLevel(\n    ribbonTexture,\n    ribbonSampler,\n    prTextureUvFromOrb(p, contourRad),\n    0.0,\n  );\n}\n@fragment\nfn ribbon_composite_fs_main(in: VOut) -> @location(0) vec4<f32> {\n  let direct = textureSampleLevel(ribbonTexture, ribbonSampler, in.uv, 0.0);\n  if (u.glassEnabled <= 0.5) { return direct; }\n  let fc = vec2<f32>(in.uv.x, 1.0 - in.uv.y) * u.size;\n  let minSize = max(min(u.size.x, u.size.y), 1.0);\n  let uv = (2.0 * fc - u.size) / minSize;\n  let rad = max(u.radius, 0.05);\n  let t = u.time * u.speed;\n  let contourRad = rad * glsContourScale(uv, t, u.contourDeform);\n  let shell = orbGlassLiquidAnim(in.uv);\n  if (length(uv) > contourRad * (1.01 + mfEdgeD(u.edgeSoftness))) {\n    return shell;\n  }\n  let p = uv / contourRad;\n  let pd = length(p);\n  let clearFa = 1.0 - smoothstep(GL_CLEAR_EA, GL_CLEAR_EB, pd);\n  let normal = glsContourNormal(uv, rad, t, u.contourDeform);\n  let edgeDepth = max(1.0 - pd, 0.0);\n  let refractionWidth = 0.015 + 0.95 * clamp(u.shellMidAlpha, 0.0, 1.0);\n  let refractionT = edgeDepth / max(refractionWidth, 0.001);\n  let refractionProfile = pow(glsRefractionProfile(refractionT), 0.68);\n  let refractionAmount = 1.6 * clamp(u.glassOpacity, 0.0, 1.0)\n                         * refractionProfile;\n  let refractedP = p - normal * refractionAmount;\n  let channelSplit = 0.14 * clamp(u.gloss, 0.0, 2.0)\n                     * clamp(u.glassOpacity, 0.0, 1.0)\n                     * refractionProfile;\n  let redSample = prSampleRibbon(refractedP - normal * channelSplit, contourRad);\n  let greenSample = prSampleRibbon(refractedP, contourRad);\n  let blueSample = prSampleRibbon(refractedP + normal * channelSplit, contourRad);\n  let refractedAlpha = max(redSample.a, max(greenSample.a, blueSample.a)) * clearFa;\n  let refracted = vec4<f32>(\n    vec3<f32>(redSample.r, greenSample.g, blueSample.b) * clearFa,\n    refractedAlpha,\n  );\n  return vec4<f32>(\n    shell.rgb + refracted.rgb * (1.0 - shell.a),\n    shell.a + refracted.a * (1.0 - shell.a),\n  );\n}";
  // Semilla del estado "thinking" (el del indicador). [0]=ancho [1]=alto [2]=fase [3]=velocidad.
  const ORB_SEED = [1, 1, 0, 1.7200000286102295, 0.699999988079071, 0.36000001430511475, 2.5999999046325684, 0.46000000834465027, 2.200000047683716, 0.07999999821186066, 0, 2, 0.800000011920929, 0.20000000298023224, 1.350000023841858, 19, 0.004999999888241291, 0, 0, 1, 0.47999998927116394, 0.10000000149011612, 2, 0.41999998688697815, 0.7699999809265137, 0.23000000417232513, 65, 0, 0, 1, 0.2199999988079071, 0.25, 0.7200000286102295, 5, 0.41999998688697815, 1.25, 0.550000011920929, 0.30000001192092896, 1.2000000476837158, 0.699999988079071, 0.03529411926865578, 0.0117647061124444, 0.054901961237192154, 1, 0.8078431487083435, 0.1725490242242813, 0.7960784435272217, 1, 1, 0.3607843220233917, 0.4431372582912445, 1, 0.48235294222831726, 0.32549020648002625, 1, 1, 1, 0.8509804010391235, 0.9411764740943909, 1, 1, 1, 1, 1, 0.8941176533699036, 0.545098066329956, 1, 1, 1, 0.47058823704719543, 0.5647059082984924, 1, 1, 0.9450980424880981, 0.9803921580314636, 1, 0.9058823585510254, 0.8509804010391235, 1, 1, 0.007843137718737125, 0.003921568859368563, 0.019607843831181526, 1, 0.8078431487083435, 0.1725490242242813, 0.7960784435272217, 1, 0.9686274528503418, 0.9843137264251709, 1, 1, 0.9372549057006836, 0.9647058844566345, 0.9921568632125854, 1, 0.8784313797950745, 0.9333333373069763, 0.9764705896377563, 1, 0.8313725590705872, 0.9019607901573181, 0.9686274528503418, 1, 0.7333333492279053, 0.8352941274642944, 0.9529411792755127, 1, 0.6509804129600525, 0.7803921699523926, 0.9411764740943909, 1, 0.529411792755127, 0.6901960968971252, 0.9215686321258545, 1, 0.43529412150382996, 0.6196078658103943, 0.9098039269447327, 1, 0.43529412150382996, 0.6196078658103943, 0.9098039269447327, 1, 0.43529412150382996, 0.6196078658103943, 0.9098039269447327, 1, 0.43529412150382996, 0.6196078658103943, 0.9098039269447327, 1, 0.43529412150382996, 0.6196078658103943, 0.9098039269447327, 1];

  let orbGpu = null; // { canvas, device, ... } listo | { perdido: true } = no reintentar
  let orbGpuIniciando = false;

  async function initOrbGpu() {
    try {
      const adapter = await navigator.gpu.requestAdapter();
      if (!adapter) throw new Error("sin adapter");
      const device = await adapter.requestDevice();
      const canvas = document.createElement("canvas");
      canvas.className = "orb";
      canvas.setAttribute("aria-hidden", "true");
      const ctx = canvas.getContext("webgpu");
      if (!ctx) throw new Error("sin contexto webgpu");
      const format = navigator.gpu.getPreferredCanvasFormat();
      ctx.configure({ device, format, alphaMode: "premultiplied" });

      const modulo = device.createShaderModule({ code: ORB_WGSL });
      const info = await modulo.getCompilationInfo();
      if (info.messages.some((m) => m.type === "error")) throw new Error("WGSL no compila");

      const pipeline = device.createRenderPipeline({
        layout: "auto",
        vertex: { module: modulo, entryPoint: "vs_main" },
        fragment: {
          module: modulo,
          entryPoint: "fs_main",
          targets: [{
            format,
            blend: {
              color: { srcFactor: "one", dstFactor: "one-minus-src-alpha", operation: "add" },
              alpha: { srcFactor: "one", dstFactor: "one-minus-src-alpha", operation: "add" },
            },
          }],
        },
        primitive: { topology: "triangle-list" },
      });
      const values = new Float32Array(ORB_SEED);
      const buffer = device.createBuffer({
        size: values.byteLength,
        usage: GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST,
      });
      const bind = device.createBindGroup({
        layout: pipeline.getBindGroupLayout(0),
        entries: [{ binding: 0, resource: { buffer } }],
      });
      device.lost.then(() => {
        orbGpu = { perdido: true };
      });

      orbGpu = { canvas, device, ctx, pipeline, buffer, bind, values, fase: 0, ultimo: null, css: 0 };
      render(); // el indicador puede estar ya montado con el canvas WebGL: esto hace el relevo

      const dibujar = (ahora) => {
        const o = orbGpu;
        if (!o || o.perdido) return;
        if (!o.canvas.isConnected) {
          // Fuera de pantalla: pausa barata y se vuelve a mirar por si reaparece.
          setTimeout(() => requestAnimationFrame(dibujar), 400);
          return;
        }
        const dpr = Math.min(window.devicePixelRatio || 1, 2);
        const px = Math.max(1, Math.floor(o.css * dpr));
        if (o.canvas.width !== px) {
          o.canvas.width = px;
          o.canvas.height = px;
        }
        // Mismo avance de fase que animation.html: la velocidad vive en values[3] y la fase
        // se normaliza por ella para que un cambio de velocidad no "salte" la animacion.
        const dt = o.ultimo === null ? 0 : Math.min(0.1, Math.max(0, (ahora - o.ultimo) / 1000));
        o.ultimo = ahora;
        o.fase += dt * Math.max(o.values[3], 0);
        o.values[0] = px;
        o.values[1] = px;
        o.values[2] = o.fase / Math.max(o.values[3], 0.001);
        o.device.queue.writeBuffer(o.buffer, 0, o.values);
        const enc = o.device.createCommandEncoder();
        const pass = enc.beginRenderPass({
          colorAttachments: [{
            view: o.ctx.getCurrentTexture().createView(),
            clearValue: { r: 0, g: 0, b: 0, a: 0 },
            loadOp: "clear",
            storeOp: "store",
          }],
        });
        pass.setPipeline(o.pipeline);
        pass.setBindGroup(0, o.bind);
        pass.draw(3);
        pass.end();
        o.device.queue.submit([enc.finish()]);
        requestAnimationFrame(dibujar);
      };
      requestAnimationFrame(dibujar);
    } catch (_) {
      // Cualquier fallo (sin soporte, driver, compilacion): WebGL toma el relevo, sin ruido.
      orbGpu = { perdido: true };
    }
  }

  function ensureOrbGpu() {
    if (window.navigator && navigator.gpu && !orbGpuIniciando) {
      orbGpuIniciando = true;
      initOrbGpu(); // async; el WebGL responde mientras tanto y el render del final releva
    }
  }

  function liquidOrb(size) {
    ensureOrbGpu();
    if (orbGpu && !orbGpu.perdido) {
      orbGpu.css = size;
      orbGpu.canvas.style.width = orbGpu.canvas.style.height = size + "px";
      return orbGpu.canvas;
    }
    return liquidOrbGl(size);
  }

  let orbShared = null; // { canvas, gl, uT, uR, vivo }

  function liquidOrbGl(size) {
    if (orbShared && orbShared.perdido) return null;
    if (!orbShared) {
      const canvas = document.createElement("canvas");
      canvas.className = "orb";
      canvas.setAttribute("aria-hidden", "true");
      const gl = canvas.getContext("webgl", { alpha: true, premultipliedAlpha: true, antialias: true });
      if (!gl) {
        orbShared = { perdido: true };
        return null;
      }
      const vertice = "attribute vec2 p;void main(){gl_Position=vec4(p,0.,1.);}";
      // El look de la referencia (animation.html, preset "Orb") es SEDA, no ruido: bandas
      // anchas de color que se doblan y giran despacio sobre una esfera con aro luminoso.
      // El intento anterior usaba fbm (ruido fractal) y por eso se veia granulado y "sucio"
      // al lado de la referencia. Aqui: cero ruido — una banda gaussiana ondulada que rota,
      // un halo calido debajo, base violeta profunda y rim rosado. Paleta anclada al vault
      // del producto pero corrida hacia magenta/rosa como la referencia.
      const fragmento =
        "precision mediump float;uniform float u_t;uniform float u_r;" +
        "void main(){vec2 uv=(gl_FragCoord.xy*2.-vec2(u_r))/u_r;float d=length(uv);float t=u_t;" +
        // La banda vive en un marco que rota muy despacio.
        "float a=t*.18;mat2 R=mat2(cos(a),-sin(a),sin(a),cos(a));vec2 p=R*uv;" +
        // Distancia (con ondulacion suave) a la banda -> gaussianas anchas, nada de ruido.
        "float band=p.y+.28*sin(p.x*1.8+t*.5)+.12*sin(p.x*3.1-t*.33);" +
        "float g1=exp(-band*band*6.);" +
        "float g2=exp(-(band-.55)*(band-.55)*3.);" +
        "float g3=exp(-(band+.6)*(band+.6)*2.5);" +
        "vec3 fondo=vec3(.16,.05,.38);" +
        "vec3 magenta=vec3(.95,.2,.75);" +
        "vec3 rosa=vec3(1.,.55,.85);" +
        "vec3 carmin=vec3(.85,.15,.35);" +
        "vec3 col=fondo;" +
        "col=mix(col,carmin,clamp(g2,0.,1.)*.9);" +
        "col=mix(col,fondo*1.25,clamp(g3,0.,1.)*.5);" +
        "col=mix(col,magenta,clamp(g1,0.,1.));" +
        "col+=rosa*g1*g1*.6;" +
        // Volumen esferico suave y aro luminoso fino, como la referencia.
        "col*=.78+.3*(1.-smoothstep(0.,1.,d));" +
        "float rim=smoothstep(.8,.98,d)*smoothstep(1.02,.94,d);" +
        "col+=vec3(1.,.8,.95)*rim*.9;" +
        "float alfa=smoothstep(1.,.96,d);" +
        "gl_FragColor=vec4(col*alfa,alfa);}"
      const compilar = (tipo, fuente) => {
        const shader = gl.createShader(tipo);
        gl.shaderSource(shader, fuente);
        gl.compileShader(shader);
        return shader;
      };
      const programa = gl.createProgram();
      gl.attachShader(programa, compilar(gl.VERTEX_SHADER, vertice));
      gl.attachShader(programa, compilar(gl.FRAGMENT_SHADER, fragmento));
      gl.linkProgram(programa);
      if (!gl.getProgramParameter(programa, gl.LINK_STATUS)) {
        orbShared = { perdido: true };
        return null;
      }
      gl.useProgram(programa);
      gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
      const p = gl.getAttribLocation(programa, "p");
      gl.enableVertexAttribArray(p);
      gl.vertexAttribPointer(p, 2, gl.FLOAT, false, 0, 0);
      orbShared = {
        canvas,
        gl,
        uT: gl.getUniformLocation(programa, "u_t"),
        uR: gl.getUniformLocation(programa, "u_r"),
      };
      const dibujar = () => {
        const orbe = orbShared;
        if (!orbe || orbe.perdido) return;
        if (!orbe.canvas.isConnected) {
          // Fuera de pantalla: no se dibuja; se vuelve a mirar con calma por si reaparece.
          setTimeout(dibujar, 400);
          return;
        }
        // Tiempo anclado al inicio de la espera: continuidad entre re-renders del sondeo.
        const t = ((Date.now() - (state.typingSince || Date.now())) % 3600000) / 1000;
        orbe.gl.uniform1f(orbe.uT, t);
        orbe.gl.drawArrays(orbe.gl.TRIANGLE_STRIP, 0, 4);
        requestAnimationFrame(dibujar);
      };
      requestAnimationFrame(dibujar);
    }
    const orbe = orbShared;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    if (orbe.canvas.width !== size * dpr) {
      orbe.canvas.width = orbe.canvas.height = size * dpr;
      orbe.gl.viewport(0, 0, size * dpr, size * dpr);
      orbe.gl.uniform1f(orbe.uR, size * dpr);
    }
    orbe.canvas.style.width = orbe.canvas.style.height = size + "px";
    return orbe.canvas;
  }

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
        const detail = data && data.detail;
        const error = new Error(typeof detail === "string" ? detail : `HTTP ${response.status}`);
        error.status = response.status;
        error.detail = detail;
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
      if (!state.activeId) state.activeId = stored.conversationId;
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
    // El limite real lo fija el backend (MAX_MESSAGE_CHARS, D-005) y viaja en la sesion:
    // copiarlo aqui significaria que subirlo en `.env` deja al widget cortando en el viejo.
    if (data.limits && data.limits.max_message_chars) state.maxChars = data.limits.max_message_chars;
    const session = {
      token: data.token,
      expiresAt: data.expires_at,
      userType: data.user.type,
      userName: data.user.name,
      userId: wantedUser,
      conversationId: data.conversation.conversation_id,
    };
    state.session = session;
    state.activeId = session.conversationId;
    state.identityError = false;
    storeSession(session);
    return session;
  }

  function dropSession() {
    state.session = null;
    state.messages = [];
    state.pending.clear();
    state.lastKey = null;
    state.firstKey = null;
    state.hasMore = false;
    state.conversations = [];
    state.activeId = null;
    state.conversation = null;
    state.threads = new Map();
    state.lastListAt = 0;
    state.seenAt = {};
    state.formDraft = {};
    state.formError = null;
    state.typingSince = null;
    storeSession(null);
  }

  // Cualquier llamada autenticada: si la sesion dejo de servir, se abre otra y se reintenta una
  // vez. Dos motivos distintos con el mismo remedio:
  //   401 → el token caduco o no vale.
  //   404 → la conversacion ya no existe en el servidor. En dev pasa cada vez que se reinicia
  //         dynamodb-local (corre en memoria y pierde las tablas); en produccion lo hara la
  //         retencion (D-014). Sin esto la pestaña queda inservible AUNQUE SE RECARGUE, porque
  //         la sesion vive en sessionStorage y sobrevive al reload: el widget seguiria pidiendo
  //         una conversacion muerta hasta cerrar la pestaña.
  async function withSession(fn) {
    const session = await ensureSession();
    try {
      return await fn(session);
    } catch (error) {
      if (error.status !== 401 && error.status !== 404) throw error;
      dropSession(); // limpia mensajes, pendientes y el cursor del sondeo
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
      if (!state.firstKey || message.message_key < state.firstKey) state.firstKey = message.message_key;
    }
    if (added) state.messages.sort((a, b) => (a.message_key < b.message_key ? -1 : 1));
    return added;
  }

  // ───────────────────────── Conversaciones: hilo del bot + casos (D-029) ─────────────────────────

  function isAnonymous() {
    return !state.session || state.session.userType !== "AUTHENTICATED";
  }

  function threadId() {
    return state.session ? state.session.conversationId : null;
  }

  function isThread(conv) {
    return !conv || conv.kind !== "CASE";
  }

  function waitingAdvisor(conv) {
    return Boolean(conv) && (conv.status === "PENDING_ADVISOR" || conv.status === "IN_ATTENTION");
  }

  function hasOpenCase() {
    return state.conversations.some((c) => c.kind === "CASE" && c.status !== "CLOSED");
  }

  /** Estado fresco de una conversacion (viene en cada sondeo): se refleja en la lista. */
  function applyConversation(conv) {
    if (!conv) return;
    if (conv.conversation_id === state.activeId) state.conversation = conv;
    const i = state.conversations.findIndex((c) => c.conversation_id === conv.conversation_id);
    if (i >= 0) state.conversations[i] = conv;
    else if (conv.kind === "CASE") state.conversations.push(conv);
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
    state.unseenBelow = 0;
    state.stickToBottom = true;
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

  /** Anonimo con la conversacion cerrada: otra sesion es otra conversacion (D-002/D-018). */
  function startNewConversation() {
    dropSession();
    state.view = "messages";
    render();
    boot();
  }

  // ───────────────────────────────── Sondeo (TD-001) ─────────────────────────────────

  async function poll() {
    if (state.loading) return;
    // El anonimo no tiene sesion hasta que abre el chat: sin sesion no hay fila que sondear
    // (y crearla desde aqui haria una conversacion por cada visitante de VMC).
    if (!state.session && !wantsAuthenticated()) return;
    state.loading = true;
    try {
      await ensureSession();
      const listDue = !isAnonymous() && Date.now() - state.lastListAt > CONFIG.listEveryMs;
      if (listDue) await fetchConversations();
      // Cerrado y autenticado: la lista ya cubrio todos los casos en UNA llamada.
      if (state.open || isAnonymous()) await pollActive();
      state.failures = 0;
      if (!state.open) updateLauncher();
    } catch (_) {
      state.failures += 1;
      render(); // muestra el aviso de sin conexion si aplica
    } finally {
      state.loading = false;
      if (state.pollAgain) {
        state.pollAgain = false;
        poll();
      } else {
        schedulePoll();
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
    const ajenos = data.messages.filter((m) => m.sender_type !== "USER").length;
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
    } catch (_) {
      /* el boton sigue ahi para reintentar */
    } finally {
      state.loadingOlder = false;
      render();
    }
  }

  function jitter(ms) {
    return Math.round(ms * (0.85 + Math.random() * 0.3));
  }

  /** Cuanto esperar hasta el proximo sondeo; 0 = nada puede llegar, no se sondea. */
  function pollDelay() {
    if (state.failures) {
      const factor = Math.pow(2, state.failures - 1);
      return jitter(Math.min(CONFIG.backoffMaxMs, CONFIG.backoffBaseMs * factor));
    }
    const conv = state.conversation;
    if (state.open) {
      if (conv && conv.status === "CLOSED") return isAnonymous() ? 0 : jitter(CONFIG.listEveryMs);
      if (state.typingSince && (!conv || conv.bot_enabled)) return jitter(CONFIG.pollWaitingMs);
      if (waitingAdvisor(conv)) return jitter(CONFIG.pollAdvisorMs);
      return jitter(CONFIG.pollOpenMs);
    }
    if (isAnonymous()) return waitingAdvisor(conv) ? jitter(CONFIG.pollAnonPendingClosedMs) : 0;
    return hasOpenCase() ? jitter(CONFIG.pollClosedMs) : 0;
  }

  function schedulePoll() {
    clearTimeout(state.pollTimer);
    if (document.visibilityState === "hidden") return; // se reanuda en visibilitychange
    if (!state.session) return;
    const delay = pollDelay();
    if (!delay) return;
    state.pollTimer = setTimeout(poll, delay);
  }

  // ───────────────────────── Formulario de asesor (D-029) ─────────────────────────

  async function submitHandoff(spec) {
    if (state.formBusy) return;
    const values = {};
    for (const field of spec.fields) {
      const value = String(state.formDraft[field.name] || "").trim();
      if (value) values[field.name] = value;
      else if (field.required) {
        state.formError = { field: field.name, message: TEXT.formRequired };
        render();
        return;
      }
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
      const conv = data.conversation;
      if (conv.conversation_id === id) {
        // Anonimo: su misma conversacion ya espera al asesor; el sondeo trae lo nuevo.
        applyConversation(conv);
        state.typingSince = null;
        await pollActive();
        render();
      } else {
        // Autenticado: se abrio un caso aparte; se entra a el y el hilo sigue con el bot.
        applyConversation(conv);
        await fetchConversations().catch(() => null);
        switchConversation(conv.conversation_id);
      }
    } catch (error) {
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

  function sendMessage(text, interaction) {
    state.stickToBottom = true; // lo propio siempre lleva la vista abajo
    state.unseenBelow = 0;
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
    try {
      const data = await withSession((session) =>
        request(
          "POST",
          `/chat/conversations/${draft.conversationId || session.conversationId}/messages`,
          Object.assign(
            { client_message_id: clientMessageId, content: draft.content },
            draft.interaction ? { interaction: draft.interaction } : null
          ),
          session.token
        )
      );
      state.pending.delete(clientMessageId);
      if (draft.conversationId === state.activeId) upsertMessages([data.message]);
      // El mensaje quedo durable (202): a partir de aqui se espera respuesta — del bot. Con
      // un asesor en el caso la espera es de una persona y no se promete "escribiendo".
      if (!state.conversation || state.conversation.bot_enabled) state.typingSince = Date.now();
      schedulePoll(); // cadencia rapida mientras se espera
    } catch (error) {
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

  const VIEW_ORDER = { home: 0, inbox: 1, messages: 1.3, help: 2 };

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
    const previousComposer = current ? current.querySelector("textarea") : null;
    const draft = previousComposer ? previousComposer.value : "";
    const caret = previousComposer ? previousComposer.selectionStart : 0;

    if (changedView && current) crossfade(current, view, direction);
    else panelEl.replaceChildren(view);

    mountAnimatedAvatars();
    const thread = view.querySelector(".thread");
    if (thread) {
      const primeraVez = previousScroll === null;
      if (primeraVez || wasAtBottom || state.stickToBottom) {
        // Al abrir el hilo se aterriza abajo sin animacion; ya dentro, cada mensaje nuevo
        // desliza suave (scroll-behavior del .thread) para que se vea de donde salio.
        thread.scrollTop = thread.scrollHeight;
        state.stickToBottom = true;
        state.unseenBelow = 0;
      } else {
        // El usuario estaba leyendo mas arriba: se respeta su punto exacto. Si el contenido
        // crecio por arriba (paginacion hacia atras), se compensa para que no se le mueva.
        const crecioArriba = thread.scrollHeight - previousHeight;
        thread.scrollTop = previousTop + (crecioArriba > 0 && previousTop < 40 ? crecioArriba : 0);
      }
    }
    const composer = view.querySelector("textarea");
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
    const open = state.open;
    launcherEl.classList.toggle("is-open", open);
    launcherEl.setAttribute("aria-label", open ? TEXT.minimize : TEXT.open);
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
      if (message.sender_type !== "SYSTEM" && message.message_type !== "SYSTEM") continue;
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
    if (isThread(state.conversation) && !state.hasMore && (hayHistorial || state.greetingVisible)) {
      items.push(
        renderBubble(
          {
            sender_type: "BOT",
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
    const ultimo = state.messages[state.messages.length - 1] || null;
    for (const message of state.messages) {
      const diaAntes = lastDay;
      pushDay(message.created_at);
      if (message.sender_type === "SYSTEM" || message.message_type === "SYSTEM") {
        items.push(renderSystemEvent(message));
        previo = null;
        continue;
      }
      const cambioDeDia = lastDay !== diaAntes;
      items.push(renderBubble(message, cambioDeDia || !sameGroup(previo, message)));
      previo = message;
      // Quick replies (D-028): SOLO bajo el ultimo mensaje del hilo y sin envios en vuelo —
      // en cuanto el usuario responde (click o texto), los botones desaparecen del render.
      if (message === ultimo && state.pending.size === 0) {
        const botones = renderQuickReplies(message) || renderHandoffForm(message);
        if (botones) items.push(botones);
      }
    }
    for (const [clientMessageId, draft] of state.pending) {
      if (draft.conversationId && draft.conversationId !== state.activeId) continue;
      pushDay(draft.createdAt);
      const propio = { sender_type: "USER", created_at: draft.createdAt };
      items.push(renderPending(clientMessageId, draft, !sameGroup(previo, propio)));
      previo = propio;
    }
    const typing = renderTyping();
    if (typing) items.push(typing);

    return h(
      "div",
      { class: "screen messages" },
      renderThreadHeader(),
      renderBanner(),
      renderStatusBanner(),
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
                  state.stickToBottom = true;
                  state.unseenBelow = 0;
                  render();
                },
              },
              ICON.chevron(),
              h("span", { text: String(state.unseenBelow) })
            )
          : null
      ),
      state.conversation && state.conversation.status === "CLOSED"
        ? renderClosedBar()
        : renderComposer()
    );
  }

  function statusLabel(conv) {
    if (!conv) return null;
    if (conv.status === "PENDING_ADVISOR") return TEXT.statusPending;
    if (conv.status === "IN_ATTENTION") return TEXT.statusAttending;
    if (conv.status === "CLOSED") return TEXT.statusClosed;
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
      h("button", { class: "icon-btn", type: "button", "aria-label": TEXT.back, onclick: back }, ICON.back()),
      caso ? null : botAvatar("avatar", true),
      h("div", { class: "bar-title" }, h("strong", { text: conversationLabel(conv) }), subtitulo),
      h("button", { class: "icon-btn", type: "button", "aria-label": TEXT.close, onclick: () => setOpen(false) }, ICON.close())
    );
  }

  function renderStatusBanner() {
    if (!waitingAdvisor(state.conversation)) return null;
    return h("div", { class: "banner banner-info", text: TEXT.waitingBanner });
  }

  /** Conversacion cerrada (D-029): de solo lectura. El anonimo abre otra sesion; el
   *  autenticado vuelve a su hilo con Subastín. */
  function renderClosedBar() {
    const anon = isAnonymous();
    return h(
      "div",
      { class: "closed-bar" },
      h("span", { text: anon ? TEXT.closedAnon : TEXT.closedCase }),
      h("button", {
        class: "qr",
        type: "button",
        text: anon ? TEXT.newConversation : TEXT.backToBot,
        onclick: () => (anon ? startNewConversation() : openThread()),
      })
    );
  }

  function shortWhen(iso) {
    const label = dayLabel(iso);
    return label === TEXT.today ? formatTime(iso) : label;
  }

  /** Lista de conversaciones del autenticado (D-029): el hilo con Subastín arriba y debajo
   *  los casos con asesor, el mas reciente primero, con su estado. */
  function renderInbox() {
    const thread = state.conversations.find((c) => c.kind !== "CASE") || null;
    const cases = state.conversations.filter((c) => c.kind === "CASE");
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
                  (conv.status === "CLOSED" ? " chip-closed" : conv.status === "IN_ATTENTION" ? " chip-live" : ""),
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
        h("button", { class: "icon-btn", type: "button", "aria-label": TEXT.close, onclick: () => setOpen(false) }, ICON.close())
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

  /** Tarjeta de formulario de asesor (D-029) bajo el mensaje del bot que la trae en metadata.
   *  Los campos vienen del servidor (nombre/correo/telefono para el anonimo, RF-003); aqui
   *  solo se dibujan y se envian: la validacion real vive en conversations/forms.py. */
  function renderHandoffForm(message) {
    const interaction = message.metadata && message.metadata.interaction;
    if (!interaction || interaction.type !== "HANDOFF_FORM" || !Array.isArray(interaction.fields)) return null;
    if (message.sender_type !== "BOT") return null;
    if (state.conversation && state.conversation.status !== "BOT_ATTENDING") return null;
    const error = state.formError;
    const fields = interaction.fields.map((field) => {
      const invalid = error && error.field === field.name;
      const attrs = {
        name: field.name,
        required: field.required ? "" : null,
        maxlength: String(field.max || state.maxChars),
        class: invalid ? "is-invalid" : null,
        autocomplete: field.type === "email" ? "email" : field.type === "tel" ? "tel" : field.name === "name" ? "name" : "off",
        oninput: (event) => {
          state.formDraft[field.name] = event.target.value;
        },
      };
      const input =
        field.type === "textarea"
          ? h("textarea", Object.assign({ rows: "3" }, attrs))
          : h("input", Object.assign({ type: field.type || "text" }, attrs));
      input.value = state.formDraft[field.name] || "";
      return h("label", {}, h("span", { text: field.label }), input);
    });
    return h(
      "form",
      {
        class: "form-card" + (firstRenderOf("form:" + message.message_id) ? " is-new" : ""),
        onsubmit: (event) => {
          event.preventDefault();
          submitHandoff(interaction);
        },
      },
      fields,
      error ? h("p", { class: "form-error", text: error.message }) : null,
      h("button", {
        class: "qr qr-solid",
        type: "submit",
        disabled: state.formBusy ? "" : null,
        text: state.formBusy ? TEXT.formSending : interaction.submit || TEXT.send,
      })
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
    if (message.sender_type === "USER") return "USER";
    if (message.sender_type === "ADVISOR") {
      return "ADVISOR:" + ((message.metadata && message.metadata.sender_name) || "");
    }
    return "BOT";
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
    const mine = message.sender_type === "USER";
    const advisor = message.sender_type === "ADVISOR";
    // El propio mensaje ya se animo como borrador: se reusa su client_message_id para que la
    // version confirmada no vuelva a entrar deslizandose.
    const fresh = firstRenderOf(message.client_message_id || message.message_id || "greeting");
    const clases =
      "row" + (mine ? " row-mine" : "") + (primero ? " is-first" : "") + (fresh ? " is-new" : "") +
      (message.isGreeting ? " is-greeting" : "");
    return h(
      "div",
      { class: clases },
      h(
        "div",
        { class: "bubble" + (mine ? " bubble-mine" : "") },
        advisor && primero
          ? h("span", {
              class: "bubble-who",
              text: (message.metadata && message.metadata.sender_name) || "Asesor",
            })
          : null,
        h("span", { class: "bubble-text" }, textWithLinks(message.content || "")),
        message.created_at ? h("span", { class: "stamp", text: formatTime(message.created_at) }) : null
      )
    );
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
  function renderQuickReplies(message) {
    const interaction = message.metadata && message.metadata.interaction;
    if (!interaction || interaction.type !== "QUICK_REPLIES") return null;
    if (message.sender_type !== "BOT" || !Array.isArray(interaction.options)) return null;
    const wrap = h(
      "div",
      { class: "quick-replies" + (firstRenderOf("qr:" + message.message_id) ? " is-new" : "") }
    );
    for (const option of interaction.options) {
      if (!option || !option.label || !option.value) continue;
      wrap.appendChild(
        h(
          "button",
          {
            class: "qr",
            type: "button",
            onclick: () =>
              sendMessage(option.label, {
                action_id: interaction.action_id,
                value: option.value,
                flow_version: interaction.flow_version,
                source_message_id: message.message_id,
              }),
          },
          option.label
        )
      );
    }
    return wrap.childNodes.length ? wrap : null;
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
    return h(
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
    if (open) {
      // Directo a mensajes (sin pasar por el home). Si un caso avanzo mientras estaba
      // cerrado, se abre en la lista para que se vea.
      state.view = !isAnonymous() && state.unread > 0 && hasOpenCase() ? "inbox" : "messages";
      state.unread = 0;
      state.stickToBottom = true;
      // Conversacion recien empezada: el saludo entra DESPUES de que el panel termino de
      // abrir (transicion de .38s), asi su fade se percibe como un mensaje y no como parte
      // del panel. Con historial el saludo ya esta arriba y esto no cambia nada.
      if (state.messages.length === 0) {
        state.greetingVisible = false;
        clearTimeout(state.greetingTimer);
        state.greetingTimer = setTimeout(() => {
          state.greetingVisible = true;
          render();
        }, 420);
      }
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
    try {
      await ensureSession();
      if (!isAnonymous() && !state.lastListAt) await fetchConversations();
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
      /* Salida larga y sin rebote para hover: el movimiento se frena solo en vez de chocar. */
      --ease-soft: cubic-bezier(.22, .68, .28, 1);
      /* Pulsacion: entra rapido y vuelve calmado, para que el clic se sienta y no golpee. */
      --ease-press: cubic-bezier(.34, .8, .3, 1);
      --shadow-vault: 0 12px 30px rgba(32, 0, 104, .13);
      --shadow-card: 0 2px 10px rgba(32, 0, 104, .08);
      font-family: "Plus Jakarta Sans", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      font-size: 15px; line-height: 1.5; color: var(--ink);
      -webkit-font-smoothing: antialiased;
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
      transition: transform .45s var(--ease-soft), box-shadow .45s var(--ease-soft);
    }
    /* El halo va como box-shadow y no como pseudo-elemento desenfocado: el z-index alto que
       necesita el boton para vivir sobre la pagina de VMC crea un contexto de apilado, y ahi
       un ::after con z-index negativo se pintaria ENCIMA del relleno en vez de detras. */
    .launcher:hover {
      transform: translateY(-2px) scale(1.025);
      box-shadow:
        rgba(255, 255, 255, .22) 0 1px 0 2px inset,
        rgba(132, 96, 229, .36) 0 16px 38px,
        rgba(237, 137, 54, .22) 0 5px 18px;
    }
    .launcher:active {
      transform: translateY(-1px) scale(.985);
      transition: transform .16s var(--ease-press), box-shadow .16s var(--ease-press);
    }
    .launcher-icon { display: grid; place-items: center; transition: transform .3s var(--ease); }
    /* OJO: nada de rotate aqui. El giro de 90° venia de cuando el icono abierto era una X
       (girarla se leia como animacion); con el chevron hacia abajo, ese giro lo dejaba
       apuntando a la izquierda. El cambio de icono ya comunica el estado. */
    .launcher.is-open .launcher-icon { transform: scale(1.06); }
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
      transform: translateY(16px) scale(.96); filter: blur(8px);
      transition: opacity .22s var(--ease), transform .3s var(--ease), filter .3s var(--ease), visibility 0s .3s;
    }
    .panel.is-open {
      opacity: 1; visibility: visible; pointer-events: auto; transform: none; filter: blur(0);
      transition: opacity .26s var(--ease-soft), transform .38s var(--ease-soft), filter .34s var(--ease-soft), visibility 0s;
    }
    @media (max-width: 480px) {
      .panel { right: 0; bottom: 0; width: 100vw; height: 100vh; border-radius: 0; transform-origin: bottom center; }
      .launcher { right: 16px; bottom: 16px; }
    }

    .screen { display: flex; flex-direction: column; height: 100%; background: var(--surface); }
    .screen.is-entering { animation: screen-in .3s var(--ease); }
    /* ── Cruce entre pestanas ──────────────────────────────────────────────────────────
       Las dos pantallas conviven un instante: la saliente se despega en position:absolute
       sobre el panel (que ya es contenedor por su position:fixed) y la entrante ocupa el
       flujo. La direccion la decide el orden de la barra inferior, asi que el movimiento
       coincide con el mapa mental de las pestanas en vez de ser un fundido cualquiera. */
    .screen.is-leaving { position: absolute; inset: 0; z-index: 1; pointer-events: none; }
    .screen.is-entering.from-right { animation: screen-from-right .46s var(--ease-soft) both; }
    .screen.is-entering.from-left { animation: screen-from-left .46s var(--ease-soft) both; }
    .screen.is-leaving.to-left { animation: screen-to-left .4s var(--ease-soft) both; }
    .screen.is-leaving.to-right { animation: screen-to-right .4s var(--ease-soft) both; }

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
    /* Dos halos de la paleta (naranja y teal) moviendose muy despacio: rompen el morado plano
       sin competir con el texto, que va en .home-top/h1 con z-index por encima. */
    .home-header::before {
      content: ""; position: absolute; inset: -35% -25% -45% -25%; pointer-events: none;
      background:
        radial-gradient(38% 44% at 80% 16%, rgba(237, 137, 54, .3), transparent 70%),
        radial-gradient(44% 50% at 10% 84%, rgba(0, 174, 177, .24), transparent 72%);
      animation: aurora 22s ease-in-out infinite alternate;
    }
    .home-top { position: relative; z-index: 1; display: flex; align-items: center; justify-content: space-between; }
    .brand { display: flex; align-items: center; }
    /* El logotipo hereda el blanco de la cabecera (fill: currentColor en el trazo del wordmark). */
    .brand svg { display: block; filter: drop-shadow(0 2px 8px rgba(11, 0, 40, .3)); }
    .home-header h1 { position: relative; z-index: 1; margin: 24px 0 0; font-size: 26px; font-weight: 700; line-height: 1.24; letter-spacing: -.01em; }
    .home-body { flex: 1; overflow-y: auto; padding: 0 16px 16px; margin-top: -18px; display: flex; flex-direction: column; gap: 12px; }
    .card {
      position: relative; background: var(--surface); border-radius: 18px; padding: 15px 17px;
      text-align: left; width: 100%; border: 1px solid var(--line);
      box-shadow: var(--shadow-card);
      transition: transform .42s var(--ease-soft), box-shadow .42s var(--ease-soft), border-color .42s var(--ease-soft);
    }
    button.card:hover { transform: translateY(-2px); box-shadow: var(--shadow-vault); border-color: rgba(132, 96, 229, .3); }
    button.card:active {
      transform: translateY(-1px) scale(.994);
      transition: transform .16s var(--ease-press), box-shadow .16s var(--ease-press);
    }
    .card-cta { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
    .card-cta strong { display: block; font-size: 16px; }
    .card-cta small { font-size: 13.5px; }
    .card-cta small, .search { color: var(--ink-soft); }
    /* Igual que el boton primario de Concorde: naranja que vira a vault, con brillo al pasar. */
    .cta-icon {
      position: relative; overflow: hidden; width: 38px; height: 38px; flex: none;
      border-radius: var(--radius-pill); color: #fff; display: grid; place-items: center;
      transform: rotate(90deg);
      background-image: linear-gradient(160deg, var(--orange-600) 0%, var(--orange-600) 40%, var(--vault-500) 100%);
      box-shadow: rgba(255, 255, 255, .28) 0 1px 0 1px inset, rgba(237, 137, 54, .3) 0 2px 8px;
      transition: box-shadow .34s var(--ease-soft), transform .34s var(--ease-soft);
    }
    .cta-icon::before {
      content: ""; position: absolute; inset: 0; border-radius: inherit;
      background-image: linear-gradient(220deg, var(--orange-400) 0%, var(--vault-400) 100%);
      opacity: 0; transition: opacity .3s var(--ease);
    }
    .cta-icon svg { position: relative; z-index: 1; }
    button.card:hover .cta-icon::before { opacity: 1; }
    button.card:hover .cta-icon {
      transform: rotate(90deg) scale(1.05);
      box-shadow: rgba(255,255,255,.28) 0 1px 0 1px inset, rgba(132, 96, 229, .3) 0 8px 20px;
    }
    .search { display: flex; align-items: center; justify-content: space-between; width: 100%; padding: 6px 0; font-weight: 600; color: var(--ink); }
    .search svg { color: var(--vault-500); transition: transform .3s var(--ease-soft); }
    .search:hover svg { transform: scale(1.1); }
    .list { list-style: none; margin: 0; padding: 0; }
    .list li { border-top: 1px solid var(--line); }
    .list li > button {
      display: flex; align-items: center; justify-content: space-between; width: 100%;
      padding: 12px 6px 12px 0; text-align: left; gap: 12px; border-radius: 10px;
      transition: background-color .28s var(--ease-soft), padding-left .28s var(--ease-soft);
    }
    .list li > button:hover { background: rgba(132, 96, 229, .06); padding-left: 9px; }
    .list li > button:active { background: rgba(132, 96, 229, .11); transition-duration: .12s; }
    .list li > button small { display: block; color: var(--ink-faint); font-size: 12.5px; }
    .list li > button svg { color: var(--vault-500); flex: none; transition: transform .3s var(--ease-soft); }
    .list li > button:hover svg { transform: translateX(4px); }
    .list-nested { margin-left: 14px; }
    .muted { color: var(--ink-faint); margin: 8px 0 0; font-size: 13.5px; }
    .hint {
      font-size: 13px; color: var(--vault-700); background: rgba(132, 96, 229, .08);
      border: 1px solid rgba(132, 96, 229, .22); border-radius: 14px; padding: 11px 13px; margin: 0;
    }

    .banner { padding: 10px 16px; font-size: 13.5px; animation: fade-in .24s var(--ease); }
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
    .bar-title strong { font-size: 16px; }
    .bar-title small { color: var(--ink-soft); font-size: 12.5px; }
    .status-line { display: flex; align-items: center; gap: 5px; }
    .status-dot { width: 7px; height: 7px; border-radius: 50%; flex: none; background: #22c55e; box-shadow: 0 0 0 0 rgba(34, 197, 94, .55); animation: status-pulse 2s infinite; }
    .icon-btn {
      width: 36px; height: 36px; border-radius: var(--radius-pill); display: grid; place-items: center;
      color: var(--ink-soft); flex: none;
      transition: background-color .26s var(--ease-soft), color .26s var(--ease-soft), transform .26s var(--ease-soft);
    }
    .icon-btn:hover { background: rgba(132, 96, 229, .09); color: var(--vault-600); }
    .icon-btn:active { transform: scale(.94); transition-duration: .14s; }
    .avatar {
      width: 36px; height: 36px; border-radius: var(--radius-pill); color: #fff; font-weight: 700;
      display: grid; place-items: center; flex: none;
      background-image: linear-gradient(150deg, var(--vault-500), var(--vault-700));
      box-shadow: 0 2px 8px rgba(32, 0, 104, .22);
    }
    .avatar-lg {
      width: 46px; height: 46px; border: 2px solid rgba(255, 255, 255, .55);
      animation: avatar-float 7s ease-in-out infinite;
    }
    .avatar-sm { width: 26px; height: 26px; font-size: 12px; align-self: flex-end; box-shadow: none; }
    /* El SVG del bot ocupa una fraccion del circulo para que respire dentro del degradado. */
    .avatar > svg { width: 68%; height: 68%; }
    .avatar-lg > svg { width: 64%; height: 64%; }
    .bot-eye {
      transform-box: fill-box; transform-origin: center;
      animation: bot-blink 6.5s var(--ease) infinite;
    }
    /* Mientras Subastin piensa, un anillo sale del avatar: dice "esta trabajando" sin texto. */
    .avatar.is-thinking { position: relative; }
    .avatar.is-thinking::after {
      content: ""; position: absolute; inset: -3px; border-radius: inherit;
      border: 2px solid rgba(132, 96, 229, .45);
      animation: ring-pulse 1.9s var(--ease) infinite;
    }

    /* ── Hilo ────────────────────────────────────────────────────────────────────────────*/
    .thread {
      flex: 1; min-width: 0; overflow-y: auto; padding: 14px 14px 16px;
      display: flex; flex-direction: column; background: var(--surface); scroll-behavior: smooth;
      /* Ancla el contenido al fondo mientras crece: el navegador compensa el alto nuevo en vez
         de que el hilo "salte" cuando entra una burbuja. */
      overflow-anchor: auto;
    }
    .thread::-webkit-scrollbar, .home-body::-webkit-scrollbar, .help-body::-webkit-scrollbar, .article::-webkit-scrollbar { width: 8px; }
    .thread::-webkit-scrollbar-thumb, .home-body::-webkit-scrollbar-thumb, .help-body::-webkit-scrollbar-thumb, .article::-webkit-scrollbar-thumb { background: rgba(132, 96, 229, .22); border-radius: var(--radius-pill); }
    .thread::-webkit-scrollbar-thumb:hover, .home-body::-webkit-scrollbar-thumb:hover { background: rgba(132, 96, 229, .38); }
    .ready { text-align: center; color: var(--ink-faint); font-size: 13.5px; margin-bottom: 10px; }
    .day { align-self: center; font-size: 11.5px; color: var(--ink-faint); text-transform: uppercase; letter-spacing: .04em; margin: 14px 0 6px; }
    /* ── Burbujas agrupadas (como WhatsApp) ────────────────────────────────────────────
       Ni avatar ni nombre por mensaje: eso vive en la cabecera. Los mensajes seguidos del
       mismo interlocutor se pegan (2 px) y solo el PRIMERO del grupo lleva cola; entre grupos
       se abre aire (10 px) para que el cambio de voz se lea sin necesidad de etiquetas. */
    .row { display: flex; max-width: 82%; align-self: flex-start; }
    .row-mine { align-self: flex-end; }
    .row + .row { margin-top: 2px; }
    .row.is-first { margin-top: 10px; }
    .thread > .row:first-child { margin-top: 0; }
    /* Solo las burbujas nuevas entran animadas (lo decide firstRenderOf en el JS). */
    .row.is-new { animation: bubble-in .38s var(--ease-soft) both; }
    .row-mine.is-new { animation-name: bubble-in-mine; }
    /* El saludo entra con un fade vertical puro (sin escala): llega como mensaje, no "brota". */
    .row.is-greeting.is-new { animation: greeting-in .45s var(--ease-soft) both; }
    /* ── Quick replies (D-028): pildoras bajo el ultimo mensaje del bot ── */
    .quick-replies { display: flex; flex-wrap: wrap; gap: 8px; margin: 8px 0 2px; max-width: 82%; }
    .quick-replies.is-new { animation: greeting-in .4s var(--ease-soft) both; }
    .qr {
      border: 1.5px solid var(--vault-500); background: var(--surface); color: var(--vault-600);
      border-radius: var(--radius-pill); padding: 8px 15px; font: inherit; font-size: 14px;
      font-weight: 600; cursor: pointer;
      transition: background-color .18s var(--ease), color .18s var(--ease), transform .18s var(--ease);
    }
    .qr:hover { background: var(--vault-500); color: #fff; transform: translateY(-1px); }
    .qr:active { transform: none; }
    .qr-solid { background: var(--vault-500); color: #fff; }
    .qr-solid:disabled { opacity: .6; cursor: default; transform: none; }
    /* ── Formulario de asesor (D-029): tarjeta bajo el mensaje del bot ── */
    .form-card {
      display: flex; flex-direction: column; gap: 10px; margin: 8px 0 2px; max-width: 92%;
      background: var(--surface); border: 1px solid var(--line); border-radius: 18px; padding: 14px;
      box-shadow: var(--shadow-card);
    }
    .form-card.is-new { animation: greeting-in .4s var(--ease-soft) both; }
    .form-card label { display: flex; flex-direction: column; gap: 4px; font-size: 12.5px; font-weight: 600; color: var(--ink-soft); }
    .form-card input, .form-card textarea {
      font: inherit; font-size: 14px; color: inherit; background: var(--surface); width: 100%;
      border: 1.5px solid var(--line-strong); border-radius: 12px; padding: 9px 11px;
    }
    .form-card input:focus, .form-card textarea:focus { outline: none; border-color: var(--vault-500); }
    .form-card .is-invalid { border-color: #d64545; }
    .form-card textarea { min-height: 72px; resize: vertical; }
    .form-card .qr { align-self: flex-end; }
    .form-error { margin: 0; color: #8a1c12; font-size: 12.5px; }
    .banner-info { background: rgba(132, 96, 229, .08); color: var(--vault-700); }
    .status-dot.is-off { background: #b3b3b3; animation: none; box-shadow: none; }
    .older { align-self: center; margin: 0 0 10px; font-size: 13px; }
    .closed-bar {
      display: flex; align-items: center; justify-content: space-between; gap: 10px;
      padding: 12px 16px; border-top: 1px solid var(--line); font-size: 13.5px; color: var(--ink-soft);
    }
    .system .link { font-size: inherit; margin-left: 4px; }
    /* ── Lista de conversaciones (D-029): el hilo con Subastín y los casos ── */
    .inbox-row { display: flex; align-items: center; gap: 12px; width: 100%; }
    .inbox-icon {
      display: inline-flex; width: 40px; height: 40px; border-radius: 50%; flex: none;
      align-items: center; justify-content: center; background: rgba(132, 96, 229, .1); color: var(--vault-600);
    }
    .inbox-meta { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; text-align: left; }
    .inbox-top { display: flex; justify-content: space-between; gap: 8px; align-items: baseline; }
    .inbox-title { font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .inbox-time { color: var(--ink-faint); font-size: 12px; flex: none; }
    .inbox-preview { color: var(--ink-soft); font-size: 13px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .chip {
      flex: none; font-size: 11px; font-weight: 700; padding: 3px 9px; border-radius: var(--radius-pill);
      background: rgba(237, 137, 54, .15); color: var(--orange-700);
    }
    .chip-live { background: rgba(20, 160, 130, .15); color: #0f6f5c; }
    .chip-closed { background: rgba(0, 0, 0, .07); color: var(--ink-faint); }
    .row-typing { animation: fade-in .2s var(--ease) both; }
    .bubble-wrap { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
    .row-mine .bubble-wrap { align-items: flex-end; }
    /* ── Pildora de "hay mensajes abajo" ───────────────────────────────────────────────── */
    .thread-wrap { position: relative; flex: 1; min-height: 0; display: flex; }
    .jump {
      position: absolute; right: 14px; bottom: 14px; z-index: 2;
      display: flex; align-items: center; gap: 5px; padding: 6px 12px 6px 9px;
      border-radius: var(--radius-pill); color: #fff; font-size: 12.5px; font-weight: 700;
      background-image: linear-gradient(150deg, var(--vault-500), var(--vault-700));
      box-shadow: 0 6px 18px rgba(32, 0, 104, .3);
      animation: jump-in .3s var(--ease-soft) both;
      transition: transform .3s var(--ease-soft), box-shadow .3s var(--ease-soft);
    }
    .jump:hover { transform: translateY(-2px); box-shadow: 0 10px 24px rgba(32, 0, 104, .32); }
    .jump:active { transform: translateY(0) scale(.97); transition-duration: .14s; }
    .jump svg { transform: rotate(90deg); }
    .bubble {
      position: relative; min-width: 0;
      background: var(--surface-soft); color: var(--ink); border: 1px solid var(--line);
      border-radius: 16px; padding: 8px 12px 8px 13px;
      white-space: pre-wrap; word-break: break-word; font-size: 15px; line-height: 1.45;
      box-shadow: 0 1px 2px rgba(32, 0, 104, .05);
    }
    /* ── Primer mensaje del grupo: SIN cola (decision 31/08) ───────────────────────────
       Se probaron tres colas (triangulo, gradiente heredado, curva con clip-path) y ninguna
       queda limpia con una burbuja en gradiente: la tecnica canonica (el SVG de WhatsApp Web)
       presupone color plano. En su lugar, el arranque de grupo se marca como Telegram: la
       esquina del lado del interlocutor se achata y entre grupos hay mas aire. */
    .row.is-first:not(.row-mine) .bubble { border-top-left-radius: 6px; }
    .row.is-first.row-mine .bubble { border-top-right-radius: 6px; }
    .bubble-mine {
      color: #fff; border: 0; padding: 8px 13px 8px 12px;
      background-image: linear-gradient(150deg, var(--vault-500) 0%, var(--vault-700) 100%);
      box-shadow: 0 2px 8px rgba(32, 0, 104, .16);
    }
    /* Nombre del asesor: solo en el primer mensaje de su grupo (el bot no lo necesita). */
    .bubble-who { display: block; font-size: 12.5px; font-weight: 700; color: var(--vault-600); margin-bottom: 2px; }
    .bubble-text { display: inline; }
    /* La hora va dentro de la burbuja, abajo a la derecha: flota, asi que si cabe se acomoda al
       final de la ultima linea y si no, baja sola. Es el comportamiento de WhatsApp. */
    .stamp {
      float: right; margin: 6px -3px -2px 10px; font-size: 11px; line-height: 1;
      color: var(--ink-faint); white-space: nowrap;
    }
    .bubble-mine .stamp { color: rgba(255, 255, 255, .72); }
    .bubble a { color: inherit; text-decoration: underline; text-underline-offset: 2px; }
    .bubble-pending { opacity: .62; }
    .bubble-failed { background-image: linear-gradient(150deg, #d14343, #b3261e); }
    .typing { display: inline-flex; align-items: center; gap: 5px; padding: 13px 16px; }
    /* El orbe liquido va "desnudo": sin burbuja detras, flotando junto al avatar. */
    .bubble.typing-orb {
      background: transparent; border: 0; box-shadow: none; padding: 2px 4px;
      display: grid; place-items: center;
    }
    .orb { display: block; border-radius: 50%; filter: drop-shadow(0 4px 12px rgba(60, 23, 130, .35)); }
    /* El robot Lottie ocupa mas que el 68% del bot estatico: su comp trae aire alrededor. */
    .avatar.is-lottie { overflow: hidden; }
    .avatar.is-lottie > svg { width: 150% !important; height: 150% !important; flex: none; }
    .typing i {
      width: 7px; height: 7px; border-radius: 50%; display: block;
      background: linear-gradient(150deg, var(--vault-400), var(--vault-600));
      animation: typing-dot 1.4s infinite var(--ease-soft);
    }
    .typing i:nth-child(2) { animation-delay: .18s; }
    .typing i:nth-child(3) { animation-delay: .36s; }
    .meta { font-size: 11.5px; color: var(--ink-faint); }
    .meta-error { color: #b3261e; }
    .system { align-self: center; display: flex; align-items: center; gap: 10px; color: var(--ink-faint); font-size: 12.5px; width: 100%; margin: 6px 0; }
    .system.is-new { animation: fade-in .3s var(--ease) both; }
    .system::before, .system::after { content: ""; flex: 1; height: 1px; background: linear-gradient(90deg, transparent, rgba(132, 96, 229, .3), transparent); }

    /* ── Compositor ──────────────────────────────────────────────────────────────────────
       Borde en gradiente igual que el Input de Concorde: vault en reposo, naranja a vault con
       foco. El textarea crece con el texto (autoGrow) hasta composerMaxPx. */
    /* Compositor de UNA caja, como Intercom: el borde degradado vive en .composer-box y
       adentro van el texto (arriba) y la fila de acciones (abajo). El texto no se mezcla con
       los botones porque son bloques apilados: el textarea termina donde empieza la fila —
       ese es su "tope" — y con texto largo hace scroll interno en su propia zona. */
    .composer { padding: 10px 12px 9px; border-top: 1px solid var(--line); background: var(--surface); }
    .composer-box {
      display: flex; flex-direction: column; border: 1.5px solid transparent; border-radius: 20px;
      background-image: linear-gradient(#fff, #fff), linear-gradient(338deg, var(--vault-500) 0%, #fff8f1 100%);
      background-origin: border-box; background-clip: padding-box, border-box;
      transition: box-shadow .22s var(--ease), background-image .22s var(--ease);
    }
    .composer-box:focus-within {
      background-image: linear-gradient(#fff, #fff), linear-gradient(148deg, var(--orange-600) 0%, var(--vault-500) 100%);
      box-shadow: rgba(237, 137, 54, .18) 0 2px 10px;
    }
    .composer-field { position: relative; min-width: 0; display: flex; }
    .composer-actions { display: flex; align-items: center; gap: 2px; padding: 0 7px 7px 9px; }
    .composer-actions .send { margin-left: auto; }
    .tool {
      width: 36px; height: 36px; display: grid; place-items: center; flex: none;
      border: 0; background: none; border-radius: var(--radius-pill); color: var(--ink-soft);
      cursor: pointer; transition: background-color .18s var(--ease), color .18s var(--ease);
    }
    .tool:hover:not([disabled]) { background: rgba(132, 96, 229, .1); color: var(--vault-600); }
    .tool[disabled] { color: var(--ink-faint); opacity: .55; cursor: default; }
    /* El contador solo aparece cerca del tope (lo decide el JS) y se posa sobre el borde. */
    .counter {
      position: absolute; right: 12px; bottom: -7px; z-index: 1;
      background: var(--surface); padding: 0 6px; border-radius: var(--radius-pill);
      font-size: 11px; font-weight: 700; color: var(--ink-faint);
      animation: fade-in .2s var(--ease) both;
    }
    .counter.is-full { color: #b3261e; }
    .counter[hidden] { display: none; }
    .composer textarea {
      flex: 1; resize: none; padding: 12px 15px 8px; font: inherit; color: var(--ink);
      border: 0; border-radius: 20px 20px 0 0; outline: none; background: transparent;
      max-height: 132px; overflow-y: hidden;
    }
    .composer textarea::placeholder { color: #6b7280; }
    .send {
      position: relative; overflow: hidden; width: 42px; height: 42px; flex: none;
      border-radius: var(--radius-pill); color: #fff; display: grid; place-items: center;
      background-image: linear-gradient(160deg, var(--orange-600) 0%, var(--orange-600) 40%, var(--vault-500) 100%);
      box-shadow: rgba(255, 255, 255, .28) 0 1px 0 1px inset, rgba(237, 137, 54, .3) 0 2px 8px;
      transition: transform .3s var(--ease-soft), box-shadow .34s var(--ease-soft);
    }
    .send::before {
      content: ""; position: absolute; inset: 0; border-radius: inherit;
      background-image: linear-gradient(220deg, var(--orange-400) 0%, var(--vault-400) 100%);
      opacity: 0; transition: opacity .3s var(--ease);
    }
    .send svg { position: relative; z-index: 1; transition: transform .3s var(--ease-soft); }
    .send:hover:not(:disabled) { transform: translateY(-1.5px) scale(1.03); box-shadow: rgba(255,255,255,.28) 0 1px 0 1px inset, rgba(132, 96, 229, .3) 0 10px 26px; }
    .send:hover:not(:disabled)::before { opacity: 1; }
    .send:hover:not(:disabled) svg { transform: translateY(-1px); }
    .send:active:not(:disabled) { transform: translateY(0) scale(.965); transition-duration: .14s; }
    /* Sin texto no hay envio: gris plano, sin brillo ni elevacion, cursor normal. */
    .send:disabled { background-image: none; background-color: var(--line-strong); box-shadow: none; cursor: default; }

    /* ── Navegacion inferior ─────────────────────────────────────────────────────────────
       La pestaña activa se marca con una barra vault que se dibuja de dentro hacia fuera. */
    .nav { display: flex; border-top: 1px solid var(--line); background: var(--surface); }
    .nav-item {
      position: relative; flex: 1; display: flex; flex-direction: column; align-items: center; gap: 3px;
      padding: 11px 0 13px; font-size: 12.5px; color: var(--ink-soft);
      transition: color .28s var(--ease-soft), background-color .28s var(--ease-soft);
    }
    /* -1px para que la barra tape la linea del borde y no quede flotando sobre ella. */
    .nav-item::after {
      content: ""; position: absolute; top: -1px; left: 50%; width: 34px; height: 3px;
      border-radius: 0 0 3px 3px; background: linear-gradient(90deg, var(--vault-500), var(--vault-700));
      transform: translate(-50%, -3px) scaleX(0); transform-origin: center;
      transition: transform .36s var(--ease-soft);
    }
    .nav-item:hover { color: var(--vault-600); background: rgba(132, 96, 229, .045); }
    .nav-item:active { background: rgba(132, 96, 229, .09); transition-duration: .12s; }
    .nav-item svg { transition: transform .32s var(--ease-soft); }
    .nav-item:hover svg { transform: translateY(-2px); }
    .nav-item.is-active svg { transform: translateY(-1px); }
    .nav-item.is-active { color: var(--vault-600); font-weight: 600; }
    .nav-item.is-active::after { transform: translate(-50%, 0) scaleX(1); }

    .help-body { flex: 1; overflow-y: auto; padding: 0 16px 16px; }
    .help-intro { display: flex; flex-direction: column; padding: 14px 0; }
    .help-intro small { color: var(--ink-soft); font-size: 13.5px; }
    .article { flex: 1; overflow-y: auto; padding: 16px; }
    .article p { margin: 0 0 12px; }

    /* ── Animaciones ─────────────────────────────────────────────────────────────────────*/
    @keyframes screen-in { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }
    @keyframes fade-in { from { opacity: 0; } to { opacity: 1; } }
    @keyframes fade-out { from { opacity: 1; } to { opacity: 0; } }
    /* La burbuja nace pequena desde su propia esquina (la de la cola) y se asienta: da la
       sensacion de que "sale" del interlocutor en vez de aparecer de la nada. */
    .row.is-new { transform-origin: bottom left; }
    .row-mine.is-new { transform-origin: bottom right; }
    @keyframes bubble-in {
      0% { opacity: 0; transform: translateY(12px) scale(.86); }
      60% { opacity: 1; transform: translateY(0) scale(1.015); }
      100% { opacity: 1; transform: none; }
    }
    @keyframes greeting-in {
      0% { opacity: 0; transform: translateY(16px); }
      100% { opacity: 1; transform: none; }
    }
    @keyframes bubble-in-mine {
      0% { opacity: 0; transform: translateY(12px) scale(.86); }
      60% { opacity: 1; transform: translateY(0) scale(1.015); }
      100% { opacity: 1; transform: none; }
    }
    @keyframes jump-in { from { opacity: 0; transform: translateY(10px) scale(.9); } to { opacity: 1; transform: none; } }
    @keyframes status-pulse { 70% { box-shadow: 0 0 0 4px rgba(34, 197, 94, 0); } 100% { box-shadow: 0 0 0 0 rgba(34, 197, 94, 0); } }
    @keyframes typing-dot {
      0%, 62%, 100% { transform: translateY(0) scale(.86); opacity: .38; }
      31% { transform: translateY(-5px) scale(1); opacity: 1; }
    }
    @keyframes screen-from-right {
      from { opacity: 0; transform: translateX(72px) scale(.97); filter: blur(12px); }
      55% { filter: blur(2px); }
      to { opacity: 1; transform: none; filter: blur(0); }
    }
    @keyframes screen-from-left {
      from { opacity: 0; transform: translateX(-72px) scale(.97); filter: blur(12px); }
      55% { filter: blur(2px); }
      to { opacity: 1; transform: none; filter: blur(0); }
    }
    @keyframes screen-to-left {
      from { opacity: 1; transform: none; filter: blur(0); }
      to { opacity: 0; transform: translateX(-52px) scale(.98); filter: blur(10px); }
    }
    @keyframes screen-to-right {
      from { opacity: 1; transform: none; filter: blur(0); }
      to { opacity: 0; transform: translateX(52px) scale(.98); filter: blur(10px); }
    }
    @keyframes aurora { from { transform: translate3d(-3%, -2%, 0) scale(1); } to { transform: translate3d(4%, 3%, 0) scale(1.09); } }
    @keyframes avatar-float { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(-3px); } }
    @keyframes bot-blink { 0%, 93%, 100% { transform: scaleY(1); } 96% { transform: scaleY(.1); } }
    @keyframes ring-pulse { 0% { transform: scale(.9); opacity: .85; } 70% { transform: scale(1.3); opacity: 0; } 100% { opacity: 0; } }
    @keyframes badge-pop { 0% { transform: scale(.4); opacity: 0; } 60% { transform: scale(1.18); opacity: 1; } 100% { transform: scale(1); } }

    /* ── Accesibilidad: menos MOVIMIENTO, no menos respuesta ──────────────────────────
       Antes esto anulaba toda transicion y animacion (.001ms). El efecto secundario era que
       en un sistema con las animaciones apagadas —Windows con MinAnimate=0, que Chrome
       traduce a prefers-reduced-motion: reduce— el widget se sentia muerto: el hover saltaba
       de golpe y las pestanas cambiaban sin transicion. Lo que molesta a quien pide menos
       movimiento son los DESPLAZAMIENTOS, los escalados y las animaciones en bucle, no que un
       color o una sombra cambien progresivamente. Asi que aqui: transiciones cortas pero
       vivas, cero recorrido y fuera lo decorativo. */
    @media (prefers-reduced-motion: reduce) {
      .root *, .root *::before, .root *::after { transition-duration: .18s !important; }
      /* Nada se desplaza ni escala al pasar el cursor o al pulsar. */
      .launcher:hover, .launcher:active, button.card:hover, button.card:active,
      .send:hover, .send:active, .send:hover svg, .icon-btn:active, .search:hover svg,
      .list li > button:hover svg, .nav-item:hover svg, .nav-item.is-active svg,
      button.card:hover .cta-icon { transform: none !important; }
      /* El icono de accion conserva su giro base: no es movimiento, es su orientacion. */
      .cta-icon, button.card:hover .cta-icon { transform: rotate(90deg) !important; }
      /* Animaciones decorativas en bucle: halos de la cabecera, flotacion, parpadeo, anillo.
         Los puntos de "escribiendo" se quedan: son pequenos y comunican un estado. */
      .home-header::before, .avatar-lg, .bot-eye, .avatar.is-thinking::after { animation: none !important; }
      .row.is-new, .jump { animation-name: fade-in !important; animation-duration: .2s !important; }
      .status-dot { animation: none !important; }
      .jump:hover, .jump:active { transform: none !important; }
      /* Panel y cruce de pantallas: solo fundido, sin recorrido ni desenfoque. */
      .panel { filter: none !important; }
      .screen.is-entering, .screen.is-leaving { animation-duration: .2s !important; }
      .screen.is-entering.from-right, .screen.is-entering.from-left { animation-name: fade-in !important; }
      .screen.is-leaving.to-left, .screen.is-leaving.to-right { animation-name: fade-out !important; }
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
    // El autenticado arranca al cargar (lista de casos para el contador del boton); el
    // anonimo recien al abrir el chat: sin sesion no hay fila en la tabla ni sondeo.
    if (wantsAuthenticated()) boot();
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
