"use client";

/**
 * Table — Generado por Concorde
 * Fuente: Figma VOYAGER · "Container" (1435:12215)
 *
 * Tabla de datos: header con gradiente morado (#8460E5 → #3B1782), texto de
 * encabezado blanco en mayúsculas, celdas con divisores #E1E3E2, contenedor
 * con radius 8 y overflow oculto. Data-driven: `columns` + `rows` (cada celda
 * es un ReactNode → texto, CheckIcon, guion, botones de icono, etc.).
 * Self-contained (CSS-in-JS, zero deps), con scroll horizontal.
 */

import { useEffect } from "react";
import type { JSX, ReactNode } from "react";

// ─── Types ────────────────────────────────────────────────────────────────────

export type TableAlign = "left" | "center" | "right";

export interface TableColumn {
  /** Texto/Nodo del encabezado */
  header: ReactNode;
  /** Alineación de la columna (default "left") */
  align?: TableAlign;
  /** Ancho fijo opcional (px o cualquier unidad CSS) */
  width?: number | string;
}

export interface TableProps {
  /** Definición de columnas (encabezados) */
  columns: TableColumn[];
  /** Filas: cada una es un arreglo de celdas alineado a `columns` */
  rows: ReactNode[][];
  /** Texto accesible de la tabla (caption, oculto visualmente) */
  caption?: string;
  className?: string;
}

// ─── Self-contained CSS ───────────────────────────────────────────────────────

const STYLE_ID = "concorde-table-styles";

const TABLE_STYLES = `
.ptable__scroll {
  width: 100%;
  overflow-x: auto;
  border-radius: 8px;
  background: #ffffff;
  box-shadow: rgba(32,0,104,0.06) 0px 1px 2px, rgba(32,0,104,0.10) 0px 12px 32px;
}
.ptable {
  border-collapse: collapse;
  width: 100%;
  font-family: var(--vmc-font-display, "Plus Jakarta Sans", -apple-system, sans-serif);
  background: #ffffff;
}
/* Header: una sola gradiente continua de izquierda a derecha sobre toda la fila */
.ptable thead tr {
  background-image: linear-gradient(90deg, #8460E5 0%, #3B1782 100%);
}
.ptable__th {
  position: relative;
  padding: 12px 24px;
  text-align: left;
  vertical-align: middle;
  white-space: nowrap;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: #ffffff;
  background: transparent;
  border-bottom: 1px solid rgba(0,0,0,0.5);
}
.ptable__td {
  padding: 18px 24px;
  vertical-align: middle;
  font-size: 14px;
  font-weight: 500;
  line-height: 20px;
  color: #070C0C;
  border-bottom: 1px solid #E1E3E2;
}
.ptable tbody tr:last-child .ptable__td { border-bottom: none; }
.ptable__align-center { text-align: center; }
.ptable__align-right { text-align: right; }
`;

let _stylesInjected = false;

// ─── Component ────────────────────────────────────────────────────────────────

function alignClass(align: TableAlign | undefined): string {
  if (align === "center") return " ptable__align-center";
  if (align === "right") return " ptable__align-right";
  return "";
}

export default function Table({ columns, rows, caption, className = "" }: TableProps): JSX.Element {
  useEffect(() => {
    if (_stylesInjected || typeof document === "undefined") return;
    if (!document.getElementById(STYLE_ID)) {
      const el = document.createElement("style");
      el.id = STYLE_ID;
      el.textContent = TABLE_STYLES;
      document.head.appendChild(el);
    }
    _stylesInjected = true;
  }, []);

  return (
    <>
      <style id={`${STYLE_ID}-ssr`} suppressHydrationWarning dangerouslySetInnerHTML={{ __html: TABLE_STYLES }} />
      <div className={`ptable__scroll ${className}`.trim()}>
        <table className="ptable">
          {caption ? <caption style={{ position: "absolute", width: 1, height: 1, overflow: "hidden", clip: "rect(0 0 0 0)" }}>{caption}</caption> : null}
          <thead>
            <tr>
              {columns.map(function renderTh(col, i) {
                return (
                  <th
                    key={i}
                    scope="col"
                    className={`ptable__th${alignClass(col.align)}`}
                    style={col.width !== undefined ? { width: col.width } : undefined}
                  >
                    {col.header}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {rows.map(function renderRow(row, r) {
              return (
                <tr key={r}>
                  {columns.map(function renderTd(col, c) {
                    return (
                      <td key={c} className={`ptable__td${alignClass(col.align)}`}>
                        {row[c]}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}
