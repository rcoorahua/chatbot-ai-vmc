
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
      /* "Live": el magenta→rosa de VMC (alert card / En Vivo), compartido con Concorde. */
      --live-500: #cc00ff; --live-600: #ff0066;
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
    /* El SVG del bot ocupa una fraccion del circulo para que respire dentro del degradado. */
    .avatar > svg { width: 68%; height: 68%; }
    .avatar-lg > svg { width: 64%; height: 64%; }
    .bot-eye {
      transform-box: fill-box; transform-origin: center;
      animation: bot-blink 6.5s var(--ease) infinite;
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
    /* Un enlace con la misma pinta que un boton (D-031: "Iniciar sesión"). */
    a.qr { display: inline-flex; align-items: center; text-decoration: none; }
    /* D-030: preguntas hermanas. Mismo boton que un quick reply pero alineado a la izquierda
       y con texto normal: son preguntas enteras, no opciones de un menu. */
    .quick-replies.related { max-width: 88%; }
    .qr-related { font-weight: 500; text-align: left; line-height: 1.3; }
    .qr-handoff { font-weight: 600; }
    /* Fuente bajo la burbuja del bot (RF-019): una linea discreta "Fuente: <titulo>" con el
       titulo subrayado, para que NO parezca un boton de pregunta. Se muestra el titulo del
       articulo, nunca la URL: cabe en una linea y, si no, se corta con puntos suspensivos. */
    .sources {
      display: flex; align-items: center; gap: 6px; max-width: 100%;
      margin: 4px 0 0 4px; font-size: 12px; line-height: 1.3; color: var(--ink-faint);
    }
    .sources-label { flex: none; }
    .source-link {
      display: inline-flex; align-items: center; gap: 3px; min-width: 0;
      color: var(--vault-600); text-decoration: underline; text-underline-offset: 2px;
    }
    .source-link:hover { color: var(--vault-700); }
    .source-title { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .source-link svg { flex: none; opacity: .7; }
    /* Texto de la burbuja en bloques (D-030): pasos con sangria colgante y aire entre ellos,
       parrafos separados por una linea en blanco del modelo. */
    .bubble-text { display: block; }
    .bubble-text .line, .bubble-text .li { display: block; }
    .bubble-text .li { display: flex; gap: 6px; margin-top: 5px; }
    .bubble-text .li-n { flex: none; font-weight: 600; color: var(--vault-600); }
    .bubble-mine .bubble-text .li-n { color: rgba(255, 255, 255, .85); }
    .bubble-text .li-t { min-width: 0; }
    .bubble-text .after-gap { margin-top: 10px; }
    .bubble-text strong { font-weight: 700; }
    /* Dentro de un item (flex) el float no aplica: la hora se alinea al final como item. */
    .bubble-text .li .stamp { float: none; margin: 0 -3px -2px auto; align-self: flex-end; }
    .banner-anon {
      display: flex; align-items: center; justify-content: space-between; gap: 12px;
      background: rgba(132, 96, 229, .08); color: var(--vault-700);
    }
    .banner-anon .link { flex: none; }
    /* ── Formulario de asesor (D-029; rediseño D-030) ── */
    /* Al ancho de las burbujas (82 %), del lado del bot: es una tarjeta del hilo, no un
       modal. Entra con un fade desde arriba mientras el compositor se retira hacia abajo, y
       la x lo devuelve con el movimiento inverso. */
    .form-card {
      display: flex; flex-direction: column; gap: 10px; margin: 10px 0 2px;
      align-self: stretch; width: 100%; max-width: none;
      background: var(--surface); border: 1px solid var(--line); border-radius: 18px; padding: 14px 16px 16px;
      box-shadow: var(--shadow-card);
    }
    /* Aviso bajo un obligatorio vacio (solo tras intentar avanzar). */
    .field-hint { color: #b3261e; font-size: 12px; font-weight: 500; margin-top: 1px; }
    /* Los botones de pregunta vuelven con fade cuando el formulario se retira. */
    .quick-replies.is-returning { animation: fade-in .3s var(--ease) both; }
    .form-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; margin-bottom: 2px; }
    .form-head strong { font-size: 15px; }
    .form-close {
      flex: none; width: 28px; height: 28px; margin: -4px -6px 0 0; display: grid; place-items: center;
      border: 0; background: none; border-radius: var(--radius-pill); color: var(--ink-faint); cursor: pointer;
      transition: background-color .18s var(--ease), color .18s var(--ease);
    }
    .form-close:hover { background: rgba(132, 96, 229, .1); color: var(--vault-600); }
    .form-card .req { color: #d64545; font-weight: 700; }
    @keyframes form-in { from { opacity: 0; transform: translateY(-12px); } to { opacity: 1; transform: none; } }
    .form-actions { display: flex; align-items: center; justify-content: flex-end; gap: 8px; }
    .form-card.is-new { animation: form-in .32s var(--ease-soft) both; }
    .form-card label { display: flex; flex-direction: column; gap: 4px; font-size: 12.5px; font-weight: 600; color: var(--ink-soft); }
    .form-card input, .form-card textarea {
      font: inherit; font-size: 14px; color: inherit; background: var(--surface); width: 100%;
      border: 1.5px solid var(--line-strong); border-radius: 12px; padding: 9px 11px;
    }
    .form-card input:focus, .form-card textarea:focus { outline: none; border-color: var(--vault-500); }
    .form-card .is-invalid { border-color: #d64545; }
    .form-card textarea { min-height: 72px; resize: vertical; }
    .form-error { margin: 0; color: #8a1c12; font-size: 12.5px; }
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
      background: linear-gradient(150deg, var(--vault-500), var(--live-500));
      animation: typing-dot 1.4s infinite var(--ease-soft);
    }
    .typing i:nth-child(2) { animation-delay: .18s; }
    .typing i:nth-child(3) { animation-delay: .36s; }
    /* Carga del hilo (2026-09-03, Aaron): mientras el saludo "llega" (~420 ms) o el primer
       sondeo no volvio, un spinner comun centrado. El margin auto lo centra en la columna
       flex del hilo. El aro es vault del design system (vault-500 sobre vault al 22%): el
       magenta live es acento del orbe, no de un control de carga. */
    .thread-loading {
      margin: auto; align-self: center; display: grid; place-items: center; padding: 20px;
      animation: fade-in .3s var(--ease) both;
    }
    .spinner {
      display: block; width: 26px; height: 26px; border-radius: 50%;
      border: 2.5px solid rgba(132, 96, 229, .22); border-top-color: var(--vault-500);
      animation: spin .8s linear infinite;
    }
    @keyframes spin { to { transform: rotate(360deg); } }
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
      /* Animaciones decorativas en bucle: halos de la cabecera, flotacion, parpadeo.
         Los puntos de "escribiendo" se quedan: son pequenos y comunican un estado. */
      .home-header::before, .avatar-lg, .bot-eye { animation: none !important; }
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
