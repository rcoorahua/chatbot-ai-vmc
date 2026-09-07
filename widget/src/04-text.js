
  /** El UNICO filtro de URLs del widget: solo http(s) llega a un href (fuentes, botones de
   *  enlace, la franja del visitante). Un `javascript:` que viniera del servidor o del
   *  storage no se convierte en enlace vivo. */
  function isHttpUrl(value) {
    return typeof value === "string" && /^https?:\/\//i.test(value);
  }

  // Enlaces como nodos <a> (nunca HTML crudo). Solo http(s), con rel="noopener".
  /** Texto de una linea con enlaces clicables y **negritas** (D-025 revisada con D-030: el
   *  unico markdown que el bot puede usar). Todo va por textContent: nada se inyecta.
   *  El patron NO usa lookbehind a proposito: en Safari/iOS hasta 16.3 un `(?<=…)` dentro
   *  de un literal es error de SINTAXIS al cargar el archivo, y el widget entero dejaba de
   *  montarse ahi (auditoria 2026-09-06). Negrita = `**`, un no-espacio, lo que sea sin
   *  asteriscos, un no-espacio, `**`. */
  function textWithLinks(text) {
    const fragment = document.createDocumentFragment();
    const pattern = /(\*\*\S(?:[^*]*?\S)?\*\*)|(https?:\/\/[^\s<>"']+)/g;
    let last = 0;
    // SAFETY: es String.prototype.matchAll sobre texto para encontrar URLs y pares de
    // asteriscos; no ejecuta comandos ni codigo. Solo alimenta textContent y href.
    for (const match of String(text || "").matchAll(pattern)) {
      if (match.index > last) fragment.appendChild(document.createTextNode(text.slice(last, match.index)));
      if (match[1]) {
        fragment.appendChild(h("strong", { text: match[1].slice(2, -2) }));
      } else {
        fragment.appendChild(
          h("a", { href: match[2], target: "_blank", rel: "noopener noreferrer", text: match[2] })
        );
      }
      last = match.index + match[0].length;
    }
    if (last < text.length) fragment.appendChild(document.createTextNode(text.slice(last)));
    return fragment;
  }

  const LIST_ITEM = /^\s*(\d{1,2}[).]|[-•])\s+(.*)$/;

  /** El cuerpo de una burbuja: cada linea es un bloque; "1) ..." es un item de lista con
   *  sangria colgante y aire entre items; una linea en blanco separa parrafos. Lo que
   *  antes era `white-space: pre-wrap` sobre un solo nodo de texto, pero con ritmo. */
  function renderRichText(text) {
    const fragment = document.createDocumentFragment();
    const lines = String(text || "").split("\n");
    let gap = false;
    for (const raw of lines) {
      const line = raw.trimEnd();
      if (!line.trim()) {
        gap = true;
        continue;
      }
      const item = line.match(LIST_ITEM);
      const block = item
        ? h("div", { class: "li" }, h("span", { class: "li-n", text: item[1] }), h("span", { class: "li-t" }, textWithLinks(item[2])))
        : h("div", { class: "line" }, textWithLinks(line.trim()));
      if (gap && fragment.childNodes.length) block.classList.add("after-gap");
      gap = false;
      fragment.appendChild(block);
    }
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
