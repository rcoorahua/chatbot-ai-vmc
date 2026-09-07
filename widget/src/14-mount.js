
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
    panelEl = h("div", {
      class: "panel",
      id: "subastin-panel",
      role: "dialog",
      "aria-modal": "false",
      "aria-label": TEXT.agent,
      "aria-hidden": "true",
    });
    launcherEl.setAttribute("aria-controls", "subastin-panel");
    launcherEl.setAttribute("aria-expanded", "false");
    panelEl.addEventListener("keydown", onPanelKeydown);
    container.append(launcherEl, panelEl);
    root.append(style, container);

    document.addEventListener("visibilitychange", onVisibilityChange);
    hostEl = host;

    render();
    // El autenticado arranca al cargar (lista de casos para el contador del boton); el
    // anonimo recien al abrir el chat: sin sesion no hay fila en la tabla ni sondeo.
    if (wantsAuthenticated()) boot();
  }

  function onVisibilityChange() {
    if (document.visibilityState === "visible") poll();
    else clearTimeout(state.pollTimer);
  }

  // ── Dialogo accesible ─────────────────────────────────────────────────────────────────
  // Escape cierra, Tab circula dentro del panel y el foco vuelve al boton al cerrar (ver
  // setOpen). El panel no es modal (aria-modal=false): la pagina de VMC sigue usable detras,
  // asi que el atrapado de foco es solo para no salir del panel con Tab sin querer.
  const FOCUSABLE =
    'button:not([disabled]), [href], input:not([disabled]), textarea:not([disabled]), ' +
    'select:not([disabled]), [tabindex]:not([tabindex="-1"])';

  function focusables() {
    return Array.from(panelEl.querySelectorAll(FOCUSABLE)).filter(
      (el) => !el.closest(".is-leaving") && el.getClientRects().length > 0
    );
  }

  function onPanelKeydown(event) {
    if (!state.open) return;
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      setOpen(false);
      return;
    }
    if (event.key !== "Tab") return;
    const items = focusables();
    if (!items.length) return;
    const first = items[0];
    const last = items[items.length - 1];
    const current = root.activeElement;
    if (event.shiftKey && (current === first || !panelEl.contains(current))) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && (current === last || !panelEl.contains(current))) {
      event.preventDefault();
      first.focus();
    }
  }

  let hostEl = null;

  /** Retira el widget de la pagina: corta requests y temporizadores, quita listeners y el
   *  nodo. `Subastin.mount()` lo vuelve a montar; un segundo <script> tambien puede hacerlo. */
  function unmount() {
    if (!hostEl) return;
    // Cerrado ANTES del reset: con el panel abierto, `reset()` programa el saludo (420 ms) y
    // ese temporizador sobrevivia al desmontaje (auditoria 2026-09-06).
    state.open = false;
    reset();
    document.removeEventListener("visibilitychange", onVisibilityChange);
    panelEl.removeEventListener("keydown", onPanelKeydown);
    for (const mounted of lottieMounts) mounted.anim.destroy();
    lottieMounts.length = 0;
    hostEl.remove();
    hostEl = null;
    root = null;
    panelEl = null;
    launcherEl = null;
    launcherIconEl = null;
    launcherBadgeEl = null;
    state.open = false;
    window.__subastinBooted = false;
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount);
  else mount();

  // Superficie para la pagina anfitriona. Ademas de abrir el chat, VMC avisa aqui los cambios
  // de sesion de su SPA (DETAILS.md §4.8 / Paso 10): sin recarga de pagina, el widget no
  // tiene otra forma segura de enterarse.
  window.Subastin = {
    open: () => setOpen(true),
    close: () => setOpen(false),
    showMessages: () => {
      state.view = "messages";
      setOpen(true);
    },
    /** VMC inicio sesion (jwt) o la cerro (null). Otra persona = sesion, mensajes y storage
     *  nuevos; la misma persona con un JWT renovado no pierde nada. */
    setIdentity: (jwt) => {
      identityOverride = jwt || null;
      state.forceAnonymous = false;
      if (state.session && state.session.identity === identityKey()) return;
      reset();
      if (state.open || wantsAuthenticated()) scheduleBoot();
    },
    /** Olvida todo (sesion, mensajes, storage) y vuelve a empezar con la identidad vigente.
     *  Idempotente: llamarlo dos veces seguidas no deja temporizadores ni requests dobles. */
    reset: () => {
      reset();
      if (state.open || wantsAuthenticated()) scheduleBoot();
    },
    mount: () => {
      if (hostEl) return;
      window.__subastinBooted = true;
      mount();
    },
    unmount,
  };
})();
