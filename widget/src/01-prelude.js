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
 * - El asesor se llega SOLO por la conversacion (D-031): no hay boton de asesor en la UI. El
 *   bot cierra cada respuesta con el mensaje sugerido "Contactar asesor" (el servidor
 *   reconoce el clic por su `value`, sin modelo) y, sin evidencia, pregunta "¿deseas
 *   contactar a un asesor?". El visitante solo tiene FAQ: en vez del formulario recibe la
 *   invitacion a iniciar sesion con su boton.
 * - Entrega en tiempo real por sondeo adaptativo (TD-001, ver CONFIG): 2 s esperando al bot,
 *   5 s con asesor, 15 s en reposo y 60 s con el panel cerrado solo si hay casos abiertos;
 *   pausado con la pestaña oculta y con backoff ante errores.
 * - Un mensaje se muestra como enviado SOLO cuando el backend confirma (RNF-003); si falla,
 *   queda en el navegador con "Reintentar" y el reintento reutiliza el mismo
 *   client_message_id para que el backend no lo duplique (RF-037/RF-038).
 */
(function () {
  "use strict";

  if (window.__subastinBooted) return;

  const settings = window.subastinSettings || {};
  const API_URL = String(settings.apiUrl || "").replace(/\/+$/, "");
  if (!API_URL) {
    // Sin marcar el arranque: la pagina puede corregir la configuracion y volver a cargar el
    // script. Antes el primer intento fallido bloqueaba cualquier reintento.
    console.error("[Subastin] falta window.subastinSettings.apiUrl; el widget no se carga");
    return;
  }
  window.__subastinBooted = true;

  const CONFIG = {
    // Cadencias del sondeo (TD-001, revisado 2026-09-02): se sondea SOLO cuando algo puede
    // llegar. Esperando al bot: rapido; caso con asesor: medio; hilo del bot en reposo: lento
    // (cubre la intervencion proactiva de D-022); panel cerrado: la lista de casos o nada.
    pollWaitingMs: 2000,
    pollAdvisorMs: 5000,
    pollOpenMs: 15000,
    pollClosedMs: 60000,
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

  // Vocabulario del backend (datos en ingles, T7): los mismos valores que `core/metadata.py`
  // y `conversations/models.py`. Antes eran literales sueltos por todo el archivo (auditoria
  // 2026-09-06): un estado nuevo o un tipo de boton nuevo se escribia de memoria.
  const STATUS = {
    BOT_ATTENDING: "BOT_ATTENDING",
    PENDING_ADVISOR: "PENDING_ADVISOR",
    IN_ATTENTION: "IN_ATTENTION",
    CLOSED: "CLOSED",
  };
  const KIND = { THREAD: "THREAD", CASE: "CASE" };
  const USER_TYPE = { AUTHENTICATED: "AUTHENTICATED", ANONYMOUS: "ANONYMOUS" };
  const SENDER = { USER: "USER", BOT: "BOT", ADVISOR: "ADVISOR", SYSTEM: "SYSTEM" };
  const MESSAGE_TYPE = { TEXT: "TEXT", SYSTEM: "SYSTEM", FORM_RESPONSE: "FORM_RESPONSE" };
  const INTERACTION = {
    QUICK_REPLIES: "QUICK_REPLIES",
    RELATED_QUESTIONS: "RELATED_QUESTIONS",
    HANDOFF_FORM: "HANDOFF_FORM",
    LINKS: "LINKS",
  };

  // Textos de la interfaz (UI en español, datos en ingles — decision T7).
  const TEXT = {
    brand: "VMC Subastas",
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
    // D-030/D-031: franja del visitante DENTRO del hilo, una vez por pestaña. Dice la regla
    // tal cual es: la conversacion vive lo que la pestaña y el asesor pide iniciar sesion.
    anonBanner:
      "Estás como visitante: tu conversación dura mientras esta pestaña esté abierta. " +
      "Para hablar con un asesor, inicia sesión en VMC.",
    anonLogin: "Iniciar sesión",
    anonBannerDismiss: "Entendido",
    // Chip de fuente bajo la respuesta del bot (RF-019): el enlace ya no va en el texto.
    sourceLabel: "Fuente",
    loadingThread: "Cargando la conversación",
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
    closedCase: "Este caso está cerrado.",
    backToBot: "Volver a Subastín",
    olderMessages: "Ver mensajes anteriores",
    formSending: "Enviando…",
    formFailed: "No se pudo enviar. Inténtalo de nuevo.",
    formRequired: "Falta llenar este campo",
    formSubmit: "Contactar",
    formClose: "Cerrar formulario",
    // Encabezado del formulario: copy de interfaz, vive aqui como el resto de los textos.
    formTitle: "Motivo de la consulta",
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
    // D-030: la franja "inicia sesion" del visitante se cierra una vez por pestaña; el flag
    // vive aqui y en sessionStorage (misma vida que la sesion anonima, nada en localStorage).
    anonBannerDismissed: false,
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
    // `dismissedForm` es el id del formulario del bot cerrado con la x; `composerReturn`
    // hace que el compositor vuelva subiendo cuando un formulario se va.
    dismissedForm: null,
    composerReturn: false,
    // Campos vacios marcados al intentar enviar (asterisco + aviso); se limpian al
    // escribir. `formEntering` pospone renders mientras el compositor se pliega;
    // `repliesReturn` hace que los botones de pregunta vuelvan con fade.
    formMissing: new Set(),
    formEntering: false,
    repliesReturn: false,
    // Hasta cuando ignorar los eventos de scroll del deslizamiento programado (alinear un
    // mensaje nuevo arriba), para no confundirlos con el usuario subiendo a leer.
    autoScrollUntil: 0,
  };
