
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
    // Chip de fuente (D-030): un enlace externo pequeño.
    link: () => svg(["M14 4h6v6", "M20 4l-9 9", "M18 13v6H5V6h6"], 13),
    x: () => svg(["M6 6l12 12M18 6L6 18"], 16),
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
   *  con CSS (clase .bot-eye) y el conjunto flota apenas al pasar el cursor. Es el avatar
   *  BASE: siempre se dibuja, y es lo que queda si no carga la animacion. Los avatares grandes
   *  (`animated`) se reemplazan por el Anima-Bot en Lottie cuando su runtime llega del CDN
   *  (ver `ensureLottie`, con SRI); los de burbuja quedan estaticos a proposito. */
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
