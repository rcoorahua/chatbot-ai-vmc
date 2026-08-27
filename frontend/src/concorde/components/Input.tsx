"use client";

/**
 * Input — Generado por Concorde
 * Fuente: Figma VOYAGER · "Input" (nodos 3008:15036 default · 3008:15028 focus · 3008:15044 error)
 *
 * Campo de texto 234×48, radio 16, relleno blanco. 3 variantes (por el borde):
 *   · default → borde gradiente 1px  #8460E5 → #FFF8F1
 *   · focus   → borde gradiente 2px  #ED8936 → #8460E5  + glow naranja
 *   · error   → borde rojo 1px #EF4444 + mensaje de ayuda rojo debajo
 *
 * Al enfocar (real) un input "default" toma automáticamente el borde de focus.
 */

import { forwardRef, useId } from "react";
import type { InputHTMLAttributes, JSX } from "react";

// ─── Types ────────────────────────────────────────────────────────────────────

export type InputVariant = "default" | "focus" | "error";

/**
 * Hereda los atributos nativos de <input> (type, name, id, placeholder, disabled,
 * aria-*, data-*, etc.) salvo onChange, que aquí entrega el string directo.
 * className se aplica al contenedor raíz (.pinput-root); el resto va al <input>.
 */
export interface InputProps
  extends Omit<InputHTMLAttributes<HTMLInputElement>, "onChange"> {
  /** Apariencia del borde (default "default"). El foco real activa "focus" solo. */
  variant?: InputVariant;
  /** Mensaje rojo bajo el campo — se muestra con variant="error" */
  errorMessage?: string;
  /** Recibe el string del input (no el evento). */
  onChange?: (value: string) => void;
}

// ─── Self-contained CSS ───────────────────────────────────────────────────────

const STYLE_ID = "concorde-input-styles";

const INPUT_STYLES = `
.pinput-root {
  width: 234px;
  max-width: 100%;
  font-family: var(--vmc-font-display, "Plus Jakarta Sans", -apple-system, sans-serif);
}
.pinput {
  display: flex;
  align-items: center;
  height: 48px;
  padding: 0 16px;
  border-radius: 16px;
  border: 1px solid transparent;
  /* Borde gradiente (default): #8460E5 → #FFF8F1 sobre relleno blanco */
  background-image: linear-gradient(#ffffff, #ffffff), linear-gradient(338deg, #8460E5 0%, #FFF8F1 100%);
  background-origin: border-box;
  background-clip: padding-box, border-box;
  transition: box-shadow 0.2s, border-color 0.2s;
}
.pinput__field {
  flex: 1;
  min-width: 0;
  width: 100%;
  border: none;
  outline: none;
  background: transparent;
  font-family: inherit;
  font-size: 16px;
  line-height: 20px;
  color: #191C1C;
}
.pinput__field::placeholder { color: #6B7280; }
.pinput__field:disabled { cursor: not-allowed; }

/* Focus — real (:focus-within) o forzado (variant="focus") */
.pinput:focus-within,
.pinput--focus {
  border-width: 2px;
  padding: 0 15px;
  background-image: linear-gradient(#ffffff, #ffffff), linear-gradient(148deg, #ED8936 0%, #8460E5 100%);
  box-shadow: rgba(237,137,54,0.15) 0px 2px 6px;
}

/* Error — borde rojo sólido + sin glow (gana sobre focus por orden/especificidad) */
.pinput--error,
.pinput--error:focus-within {
  border: 1px solid #EF4444;
  padding: 0 16px;
  background-image: none;
  background-color: #ffffff;
  box-shadow: none;
}
.pinput__msg {
  margin: 6px 0 0 4px;
  font-size: 13px;
  line-height: 18px;
  color: #EF4444;
}

.pinput--disabled { opacity: 0.6; }

@media (prefers-reduced-motion: reduce) {
  .pinput { transition: none; }
}
`;

let _stylesInjected = false;

// ─── Component ────────────────────────────────────────────────────────────────

const Input = forwardRef<HTMLInputElement, InputProps>(function Input({
  variant = "default",
  type = "text",
  disabled = false,
  errorMessage = "Ingresa un correo válido",
  onChange,
  className = "",
  ...rest
}, ref): JSX.Element {
  const uid = useId().replace(/:/g, "-");
  const msgId = `${uid}-msg`;
  const showMsg = variant === "error" && Boolean(errorMessage);

  if (typeof document !== "undefined" && !_stylesInjected) {
    if (!document.getElementById(STYLE_ID)) {
      const el = document.createElement("style");
      el.id = STYLE_ID;
      el.textContent = INPUT_STYLES;
      document.head.appendChild(el);
    }
    _stylesInjected = true;
  }

  const boxClass = [
    "pinput",
    variant === "focus" ? "pinput--focus" : "",
    variant === "error" ? "pinput--error" : "",
    disabled ? "pinput--disabled" : "",
  ].filter(Boolean).join(" ");

  return (
    <>
      <style id={`${STYLE_ID}-ssr`} suppressHydrationWarning dangerouslySetInnerHTML={{ __html: INPUT_STYLES }} />
      <div className={["pinput-root", className].filter(Boolean).join(" ")}>
        <div className={boxClass}>
          <input
            ref={ref}
            {...rest}
            className="pinput__field"
            type={type}
            disabled={disabled}
            onChange={function handle(e) { onChange?.(e.target.value); }}
            aria-invalid={variant === "error" ? true : rest["aria-invalid"]}
            aria-describedby={showMsg ? msgId : rest["aria-describedby"]}
          />
        </div>
        {showMsg ? <p className="pinput__msg" id={msgId}>{errorMessage}</p> : null}
      </div>
    </>
  );
});

export default Input;
