
  /** El formulario de asesor que esta a la vista, o null: el que el bot dejo como ULTIMO
   *  mensaje (D-029), salvo que se haya cerrado con la x. Solo con el bot atendiendo:
   *  derivada o cerrada, no hay nada que pedir. */
  function visibleForm() {
    if (state.conversation && state.conversation.status !== STATUS.BOT_ATTENDING) return null;
    const ultimo = lastMessage();
    if (!ultimo || state.pending.size || ultimo.sender_type !== SENDER.BOT) return null;
    const interaction = ultimo.metadata && ultimo.metadata.interaction;
    if (!interaction || interaction.type !== INTERACTION.HANDOFF_FORM || !Array.isArray(interaction.fields)) return null;
    if (state.dismissedForm === ultimo.message_id) return null;
    return { spec: interaction, key: "form:" + ultimo.message_id, messageId: ultimo.message_id };
  }

  /** Tarjeta del formulario (D-029, rediseño D-030; un solo paso desde D-031): a todo el
   *  ancho, con una x que la cierra, y la validacion al INTENTAR enviar: un campo vacio
   *  recien entonces gana su asterisco y su aviso ("Falta llenar este campo"), que se van al
   *  escribir. Los campos vienen del servidor (asunto, detalle y correo si hace falta); aqui
   *  solo se dibujan y se envian: la validacion real vive en conversations/forms.py. */
  function renderHandoffForm(spec, key) {
    const error = state.formError;
    const fields = spec.fields.map((field) => {
      const serverError = error && error.field === field.name ? error.message : null;
      const flagged = state.formMissing.has(field.name) || Boolean(serverError);
      const attrs = {
        name: field.name,
        maxlength: String(field.max || state.maxChars),
        class: flagged ? "is-invalid" : null,
        autocomplete: field.type === "email" ? "email" : "off",
        oninput: (event) => {
          state.formDraft[field.name] = event.target.value;
          // Al escribir se retira la marca de ESE campo: dejarla en rojo mientras lo corrigen
          // es ruido. El servidor vuelve a evaluar al enviar.
          if (!state.formMissing.has(field.name) && !(state.formError && state.formError.field === field.name)) return;
          state.formMissing.delete(field.name);
          if (state.formError && state.formError.field === field.name) state.formError = null;
          const label = event.target.closest("label");
          event.target.classList.remove("is-invalid");
          for (const marca of label.querySelectorAll(".req, .field-hint")) marca.remove();
        },
      };
      const input =
        field.type === "textarea"
          ? h("textarea", Object.assign({ rows: "3" }, attrs))
          : h("input", Object.assign({ type: field.type || "text" }, attrs));
      input.value = state.formDraft[field.name] || "";
      return h(
        "label",
        {},
        h("span", {}, field.label, flagged ? h("b", { class: "req", text: " *" }) : null),
        input,
        flagged ? h("small", { class: "field-hint", text: serverError || TEXT.formRequired }) : null
      );
    });
    // Siempre activo (salvo enviando): la validacion es al pulsar.
    const submitBtn = h("button", {
      class: "qr qr-solid",
      type: "submit",
      disabled: state.formBusy ? "" : null,
      text: state.formBusy ? TEXT.formSending : spec.submit || TEXT.formSubmit,
    });
    const cabecera = h(
      "div",
      { class: "form-head" },
      h("strong", { text: TEXT.formTitle }),
      h("button", { class: "form-close", type: "button", "aria-label": TEXT.formClose, title: TEXT.formClose, onclick: () => closeForm() }, ICON.x())
    );
    return h(
      "form",
      {
        class: "form-card" + (firstRenderOf(key) ? " is-new" : ""),
        onsubmit: (event) => {
          event.preventDefault();
          submitHandoff(spec);
        },
      },
      cabecera,
      fields,
      // Un error sin campo (409, red) va aqui; el de un campo ya se ve debajo de ese campo.
      error && !error.field ? h("p", { class: "form-error", text: error.message }) : null,
      h("div", { class: "form-actions" }, submitBtn)
    );
  }

  function reducedMotion() {
    return window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  const MOTION_EASE = "cubic-bezier(.25,.8,.25,1)";

  /** Llama a `done` UNA vez: al terminar `anim` o, por si el evento no llega, a los `ms`. */
  function whenDone(anim, done, ms) {
    let hecho = false;
    const finish = () => {
      if (hecho) return;
      hecho = true;
      done();
    };
    if (anim) anim.addEventListener("finish", finish);
    setTimeout(finish, ms);
  }

  /** El compositor se pliega hacia abajo: su altura baja a cero (el hilo crece y el
   *  formulario lo "empuja"), se desliza y se desvanece. Web Animations sobre el DOM vivo,
   *  porque el render siguiente lo reemplaza entero. */
  function collapseComposer(done) {
    const el = panelEl.querySelector(".composer");
    if (!el || reducedMotion() || !el.animate) return done();
    const h = el.offsetHeight;
    el.style.overflow = "hidden";
    el.style.pointerEvents = "none";
    const anim = el.animate(
      [
        { height: h + "px", opacity: 1, transform: "none" },
        { height: "0px", paddingTop: "0px", paddingBottom: "0px", opacity: 0, transform: "translateY(60%)" },
      ],
      { duration: 300, easing: MOTION_EASE, fill: "forwards" }
    );
    whenDone(anim, done, 420);
  }

  /** El compositor vuelve subiendo desde abajo, a la inversa del pliegue. Se llama con el
   *  elemento ya montado (rAF tras el render). */
  function expandComposer(el) {
    if (!el || reducedMotion() || !el.animate) return;
    const h = el.offsetHeight;
    el.style.overflow = "hidden";
    const anim = el.animate(
      [
        { height: "0px", paddingTop: "0px", paddingBottom: "0px", opacity: 0, transform: "translateY(60%)" },
        { height: h + "px", opacity: 1, transform: "none" },
      ],
      { duration: 320, easing: MOTION_EASE }
    );
    whenDone(anim, () => {
      el.style.overflow = "";
    }, 450);
  }

  /** Los botones de pregunta se van con un fade mientras el formulario esta abierto. */
  function fadeOutReplies() {
    if (reducedMotion()) return;
    for (const el of panelEl.querySelectorAll(".quick-replies")) {
      if (el.animate) el.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 200, easing: MOTION_EASE, fill: "forwards" });
    }
  }

  /** El formulario se va (fade hacia arriba) y despues `done`. */
  function fadeOutForm(done) {
    const el = panelEl.querySelector(".form-card");
    if (!el || reducedMotion() || !el.animate) return done();
    el.style.pointerEvents = "none";
    const anim = el.animate(
      [{ opacity: 1, transform: "none" }, { opacity: 0, transform: "translateY(-10px)" }],
      { duration: 220, easing: MOTION_EASE, fill: "forwards" }
    );
    whenDone(anim, done, 320);
  }

  /** Lo que pasa cuando un formulario deja de estar a la vista (x o envio): el compositor
   *  vuelve subiendo y los botones de pregunta reaparecen con fade. */
  function markFormGone() {
    state.formError = null;
    state.formMissing = new Set();
    state.composerReturn = true;
    state.repliesReturn = true;
  }

  /** La x del formulario: se va con suavidad y el compositor vuelve subiendo. Lo escrito se
   *  conserva en `formDraft` por si el bot vuelve a ofrecerlo. */
  function closeForm() {
    // Se anota QUE formulario se cierra antes del fade: si en esos 300 ms llega un mensaje
    // del bot, leer "el ultimo" despues descartaba el id equivocado y el formulario volvia a
    // aparecer (auditoria 2026-09-06).
    const form = visibleForm();
    fadeOutForm(() => {
      if (form) state.dismissedForm = form.messageId;
      markFormGone();
      render();
    });
  }
