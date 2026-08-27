"use client";

/**
 * TabSelector — Generado por Concorde
 * Fuente: Figma VOYAGER · "RadioGroup" (nodo 3008:15095)
 *
 * Selector tipo segmented/tab: contenedor pill blanco (radio 24.5, borde
 * gradiente #8460E5 → #FFF8F1) con N opciones. La opción activa lleva relleno
 * gradiente oscuro (#8460E5 → #3B1782), borde gradiente (white → #F4AC59 →
 * #8460E5 → white), texto blanco y sombra; las inactivas llevan texto en
 * gradiente lila (#8460E5 → #3B1782). Controlado o no controlado.
 */

import { useEffect, useId, useState } from "react";
import type { JSX } from "react";

// ─── Types ────────────────────────────────────────────────────────────────────

export interface TabSelectorProps {
  /** Etiquetas de las opciones */
  options: string[];
  /** Índice activo (controlado, 0-based) */
  value?: number;
  /** Índice inicial (no controlado, default 0) */
  defaultValue?: number;
  /** Callback al cambiar de opción */
  onChange?: (index: number) => void;
  "aria-label"?: string;
  className?: string;
}

// ─── Self-contained CSS ───────────────────────────────────────────────────────

const STYLE_ID = "concorde-tabselector-styles";

const TABSELECTOR_STYLES = `
.ptabs {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 49px;
  padding: 0 7px;
  border-radius: 24.5px;
  border: 1px solid transparent;
  background-image: linear-gradient(#ffffff, #ffffff), linear-gradient(330deg, #8460E5 0%, #FFF8F1 100%);
  background-origin: border-box;
  background-clip: padding-box, border-box;
  font-family: var(--vmc-font-display, "Plus Jakarta Sans", -apple-system, sans-serif);
}
.ptabs__tab {
  appearance: none;
  box-sizing: border-box;
  min-width: 83px;
  height: 34px;
  padding: 0 16px;
  border: 2px solid transparent;
  border-radius: 17px;
  white-space: nowrap;
  background: transparent;
  font-family: inherit;
  font-size: 12px;
  font-weight: 600;
  line-height: 16px;
  cursor: pointer;
  /* inactivo: texto en gradiente lila */
  color: #3B1782;
  background-image: linear-gradient(135deg, #8460E5 0%, #3B1782 100%);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
  transition: transform 0.16s, box-shadow 0.2s, opacity 0.16s;
}
.ptabs__tab:hover { opacity: 0.78; }
.ptabs__tab:active { transform: scale(0.97); }
.ptabs__tab:focus-visible { outline: 2px solid #8460E5; outline-offset: 2px; }
.ptabs__tab--active {
  color: #ffffff;
  -webkit-text-fill-color: #ffffff;
  background-image:
    linear-gradient(150deg, #8460E5 0%, #3B1782 100%),
    linear-gradient(120deg, #ffffff 0%, #F4AC59 22%, #8460E5 75%, #ffffff 100%);
  background-origin: border-box;
  background-clip: padding-box, border-box;
  box-shadow: rgba(32,0,104,0.2) 0px 8px 16px;
}
.ptabs__tab--active:hover { opacity: 1; }
@media (prefers-reduced-motion: reduce) {
  .ptabs__tab { transition: none; }
}
`;

let _stylesInjected = false;

// ─── Component ────────────────────────────────────────────────────────────────

export default function TabSelector({
  options,
  value,
  defaultValue = 0,
  onChange,
  "aria-label": ariaLabel,
  className = "",
}: TabSelectorProps): JSX.Element {
  const uid = useId().replace(/:/g, "-");
  const controlled = value !== undefined;
  const [internal, setInternal] = useState(defaultValue);
  const active = controlled ? value : internal;

  function select(i: number): void {
    if (!controlled) setInternal(i);
    onChange?.(i);
  }

  useEffect(() => {
    if (_stylesInjected || typeof document === "undefined") return;
    if (!document.getElementById(STYLE_ID)) {
      const el = document.createElement("style");
      el.id = STYLE_ID;
      el.textContent = TABSELECTOR_STYLES;
      document.head.appendChild(el);
    }
    _stylesInjected = true;
  }, []);

  return (
    <>
      <style id={`${STYLE_ID}-ssr`} suppressHydrationWarning dangerouslySetInnerHTML={{ __html: TABSELECTOR_STYLES }} />
      <div className={["ptabs", className].filter(Boolean).join(" ")} role="tablist" aria-label={ariaLabel}>
        {options.map((label, i) => {
          const isActive = i === active;
          return (
            <button
              key={`${uid}-${i}`}
              type="button"
              role="tab"
              aria-selected={isActive}
              className={["ptabs__tab", isActive ? "ptabs__tab--active" : ""].filter(Boolean).join(" ")}
              onClick={function pick() { select(i); }}
            >
              {label}
            </button>
          );
        })}
      </div>
    </>
  );
}
