/*
 * Arma widget/subastin.js concatenando los fragmentos de widget/src/ en orden de nombre.
 *
 * Por que existe: el widget se embebe en VMC como UN archivo sin build ni dependencias (esa
 * propiedad NO cambia: lo que VMC sirve sigue siendo subastin.js, versionado en el repo). Lo
 * que cambia es donde se EDITA: 3.500 lineas en un solo archivo hacian que cualquier par de
 * cambios chocara y que leer el sondeo obligara a hojear el shader del orbe.
 *
 * Los fragmentos son partes del cuerpo de UNA misma IIFE, no modulos: comparten el closure
 * (state, session, render...) tal como antes. Por eso un fragmento suelto no es JS valido y
 * `node --check` corre sobre el bundle, no sobre las partes.
 *
 *   node widget/build.mjs           # regenera widget/subastin.js
 *   node widget/build.mjs --check   # falla si el bundle no coincide con src/ (lo corre el CI)
 */
import { readdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const WIDGET_DIR = dirname(fileURLToPath(import.meta.url));
const SRC_DIR = join(WIDGET_DIR, "src");
const BUNDLE = join(WIDGET_DIR, "subastin.js");

const BANNER = `/* GENERADO por widget/build.mjs — NO EDITAR A MANO.
 * Las fuentes son widget/src/*.js; tras tocarlas, corre \`node widget/build.mjs\`.
 * El archivo se versiona para que VMC siga sirviendo un solo JS sin build.
 */
`;

function parts() {
  const files = readdirSync(SRC_DIR)
    .filter((name) => name.endsWith(".js"))
    .sort();
  if (!files.length) throw new Error(`no hay fragmentos en ${SRC_DIR}`);
  return files;
}

/** Concatena los fragmentos TAL CUAL, sin normalizar espacios: el bundle es byte a byte lo que
 *  suman las partes, asi el corte del archivo no cambio ni una linea del JS que sirve VMC. */
function build() {
  const cuerpo = parts()
    .map((name) => readFileSync(join(SRC_DIR, name), "utf8"))
    .join("");
  return lf(`${BANNER}${cuerpo}`);
}

/** El repo guarda LF, pero un checkout en Windows entrega CRLF: sin normalizar, `--check`
 *  fallaba en local y pasaba en CI por el fin de linea, no por el contenido. */
function lf(texto) {
  return texto.replace(/\r\n/g, "\n");
}

const esperado = build();

if (process.argv.includes("--check")) {
  let actual = "";
  try {
    actual = readFileSync(BUNDLE, "utf8");
  } catch {
    console.error("widget/subastin.js no existe; corre `node widget/build.mjs`");
    process.exit(1);
  }
  if (lf(actual) !== esperado) {
    console.error(
      "widget/subastin.js no coincide con widget/src/*.js.\n" +
        "Corre `node widget/build.mjs` y commitea el resultado.",
    );
    process.exit(1);
  }
  console.log(`widget/subastin.js al dia (${parts().length} fragmentos)`);
} else {
  writeFileSync(BUNDLE, esperado);
  console.log(`widget/subastin.js generado desde ${parts().length} fragmentos`);
}
