
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

  // ── Identidad viva ─────────────────────────────────────────────────────────────────────
  // El JWT de VMC se lee EN VIVO, no una vez al cargar: en una SPA el usuario cambia (login,
  // logout, otra cuenta) sin recargar la pagina, y el widget seguia con el token y el historial
  // del usuario anterior (DETAILS.md §4.8). VMC avisa con `Subastin.setIdentity(jwt)` (o
  // `setIdentity(null)` al cerrar sesion); si no avisa, se mira `window.subastinSettings`
  // antes de cada request y cualquier cambio reinicia la sesion.
  let identityOverride; // undefined = manda la pagina; null = anonimo por orden de VMC

  function currentJwt() {
    if (identityOverride !== undefined) return identityOverride;
    // Manda el objeto VIVO: si VMC lo reasigna sin `userJwt` (logout), eso es un logout, no
    // un motivo para volver al JWT que se leyo al cargar.
    const live = window.subastinSettings;
    if (live && typeof live === "object") return live.userJwt || null;
    return settings.userJwt || null;
  }

  /** Con quien se esta hablando, para invalidar la cache: NO es una verificacion de seguridad
   *  (esa la hace el backend con la firma del JWT); solo dice si la sesion guardada es de
   *  esta misma persona. */
  function identityKey() {
    const jwt = currentJwt();
    if (!jwt || state.forceAnonymous) return "anon";
    return "user:" + subjectOf(jwt);
  }

  function wantsAuthenticated() {
    return Boolean(currentJwt()) && !state.forceAnonymous;
  }

  // Generacion de la sesion: sube en cada reset. Una request que empezo en la generacion
  // anterior (otro usuario) se descarta al volver, aunque el servidor haya respondido bien —
  // nada de lo que traiga puede tocar el estado del usuario actual.
  let generation = 0;
  const inflight = new Set(); // AbortControllers vivos, para cortarlos al resetear

  function staleError() {
    const error = new Error("stale");
    error.stale = true;
    return error;
  }

  function isStale(error) {
    return Boolean(error && error.stale);
  }

  async function request(method, path, body, token) {
    const gen = generation;
    const controller = new AbortController();
    inflight.add(controller);
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
      if (gen !== generation) throw staleError(); // otro usuario desde que salio: se descarta
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
      if (gen !== generation || isStale(error)) throw staleError();
      if (!error.status) state.offline = true; // red caida o timeout, no un rechazo del backend
      throw error;
    } finally {
      clearTimeout(timer);
      inflight.delete(controller);
    }
  }

  async function ensureSession() {
    const identity = identityKey();
    if (state.session && state.session.identity !== identity) {
      // La pagina cambio de usuario sin avisar (SPA): nada de lo anterior puede seguir en
      // pantalla ni salir en una request. Se reinicia, se programa UN arranque limpio para
      // el usuario nuevo y la operacion que lo descubrio se descarta (era del anterior).
      reset();
      if (state.open || wantsAuthenticated()) scheduleBoot();
      throw staleError();
    }
    if (state.session) return state.session;
    const wantAuth = wantsAuthenticated();
    const jwt = wantAuth ? currentJwt() : null;
    const wantedUser = wantAuth ? subjectOf(jwt) : null;
    const stored = loadStoredSession();
    const stillValid =
      stored &&
      stored.identity === identity &&
      stored.expiresAt * 1000 > Date.now() + 60000 &&
      stored.userType === (wantAuth ? USER_TYPE.AUTHENTICATED : USER_TYPE.ANONYMOUS) &&
      (!wantAuth || stored.userId === wantedUser);
    if (stillValid) {
      state.session = stored;
      if (!state.activeId) state.activeId = stored.conversationId;
      return stored;
    }

    const payload = wantAuth ? { user_jwt: jwt } : {};
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
      // D-031: a donde se manda al visitante a iniciar sesion (la URL la decide el servidor;
      // solo http(s), como cualquier otro enlace que el widget dibuja).
      loginUrl: data.links && isHttpUrl(data.links.login) ? data.links.login : null,
      identity,
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
    state.dismissedForm = null;
    state.formMissing = new Set();
    state.typingSince = null;
    storeSession(null);
  }

  /** Borron y cuenta nueva: corta las requests en vuelo, apaga todos los temporizadores y
   *  olvida sesion, mensajes y storage. Es lo que pasa al cambiar de usuario (login, logout,
   *  otra cuenta) y lo que expone `Subastin.reset()`. Idempotente: dos seguidos no dejan
   *  temporizadores ni requests duplicados, porque el segundo no encuentra nada que cortar.
   *  No arranca nada: quien lo llama decide si vuelve a abrir sesion (`boot`). */
  function reset() {
    generation += 1;
    for (const controller of inflight) controller.abort();
    inflight.clear();
    clearTimeout(state.pollTimer);
    clearTimeout(state.greetingTimer);
    clearTimeout(state.typingTimer);
    state.pollTimer = null;
    state.greetingTimer = null;
    state.typingTimer = null;
    booting = false;
    state.loading = false;
    state.pollAgain = false;
    state.loadingOlder = false;
    state.formBusy = false;
    state.failures = 0;
    state.unread = 0;
    state.unseenBelow = 0;
    state.identityError = false;
    state.greetingVisible = false;
    state.seen = new Set();
    // Banderas de animacion y navegacion: un reset a mitad de un pliegue del compositor
    // dejaba `formEntering` en true y los renders se posponian hasta que un temporizador
    // ajeno lo soltara (auditoria 2026-09-06).
    state.formEntering = false;
    state.composerReturn = false;
    state.repliesReturn = false;
    state.helpArticle = null;
    state.stickToBottom = true;
    dibujandoFormulario = false;
    clearTimeout(bootTimer);
    bootTimer = null;
    dropSession();
    lastViewKey = null;
    render();
    // Con el panel abierto, la conversacion nueva tiene que presentarse igual que al abrir:
    // sin esto, cambiar de usuario dejaba el hilo vacio y sin saludo hasta reabrir.
    if (state.open) scheduleGreeting();
  }

  // El arranque tras un reset va en un temporizador de 0 ms: dos `reset()` seguidos (o un
  // reset y un setIdentity en el mismo tick) producen UN solo arranque y una sola sesion,
  // en vez de abrir dos y abortar la primera a medio camino.
  let bootTimer = null;
  function scheduleBoot() {
    clearTimeout(bootTimer);
    bootTimer = setTimeout(() => {
      bootTimer = null;
      boot();
    }, 0);
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
    const gen = generation;
    const session = await ensureSession();
    // Cambio de usuario mientras se abria la sesion: lo que se iba a pedir era del anterior.
    if (gen !== generation) throw staleError();
    try {
      return await fn(session);
    } catch (error) {
      if (isStale(error) || (error.status !== 401 && error.status !== 404)) throw error;
      dropSession(); // limpia mensajes, pendientes y el cursor del sondeo
      return fn(await ensureSession());
    }
  }
