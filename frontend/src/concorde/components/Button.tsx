// Button.tsx — Generado por Concorde
// Fuente: https://voyager-ds.vercel.app/preview/components/pase1
// Generado: 2026-05-25
// EDITAR LIBREMENTE después de generar

"use client";

import { forwardRef } from "react";
import type { ButtonHTMLAttributes, JSX, ReactNode } from "react";

export type ButtonVariant =
  | "primary"
  | "negotiable"
  | "secondary"
  | "secondary-sm"
  | "ghost"
  | "outline"
  | "sm-guest"
  | "sm-logged-in";

/**
 * Hereda todos los atributos nativos de <button> (type, name, className, style,
 * onMouseEnter, data-*, etc.) — basta con props, no hace falta editar el archivo.
 */
export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  /** Estilo visual del botón. */
  variant?: ButtonVariant;
  /** Ícono opcional en el slot circular (variantes sm-guest, secondary-sm, sm-logged-in). */
  icon?: ReactNode;
  /** Nombre de usuario — usado cuando variant="sm-logged-in". */
  username?: string;
}

// ── CSS self-contained ────────────────────────────────────────────────────

const BUTTON_STYLES = `
@property --vbtn-angle { syntax: "<angle>"; inherits: false; initial-value: 135deg; }
@property --vbtn-stop-a { syntax: "<color>"; inherits: false; initial-value: oklch(0.72 0.16 55); }
@property --vbtn-stop-b { syntax: "<color>"; inherits: false; initial-value: oklch(0.55 0.22 285); }
@property --vsec-angle { syntax: "<angle>"; inherits: false; initial-value: 160deg; }
@property --vsec-stop-a { syntax: "<color>"; inherits: false; initial-value: oklch(0.38 0.20 285); }
@property --vsec-stop-b { syntax: "<color>"; inherits: false; initial-value: oklch(0.28 0.18 285); }
@property --vneg-angle { syntax: "<angle>"; inherits: false; initial-value: 135deg; }
@property --vneg-stop-a { syntax: "<color>"; inherits: false; initial-value: #00aeb1; }
@property --vneg-stop-b { syntax: "<color>"; inherits: false; initial-value: #8460e5; }
@property --vss-angle { syntax: "<angle>"; inherits: false; initial-value: 160deg; }
@property --vss-stop-a { syntax: "<color>"; inherits: false; initial-value: #8460e5; }
@property --vss-stop-b { syntax: "<color>"; inherits: false; initial-value: #3b1782; }

/* ── primary ─────────────────────────────────────────────────────────── */
.pvbtn {
  --vbtn-stop-a: var(--vmc-color-orange-600, #ed8936);
  --vbtn-stop-b: var(--vmc-color-vault-500, #8460e5);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 48px;
  padding: 0 56px;
  border-radius: var(--vmc-radius-full, 9999px);
  /* Borde GRADIENTE de Figma (1130:1778): white → #FBC47D 25% → #AE8EFF 75% → white */
  border: 2px solid transparent;
  cursor: pointer;
  position: relative;
  overflow: hidden;
  font-family: var(--vmc-font-display, "Plus Jakarta Sans", sans-serif);
  font-size: 16px;
  line-height: 20px;
  font-weight: 600;
  color: var(--vmc-color-base-white, #ffffff);
  text-shadow: rgba(0,0,0,0.25) 0 1px 3px;
  background-image:
    linear-gradient(var(--vbtn-angle), var(--vbtn-stop-a) 0%, var(--vbtn-stop-a) 40%, var(--vbtn-stop-b) 100%),
    linear-gradient(135deg, #ffffff 0%, #fbc47d 25%, #ae8eff 75%, #ffffff 100%);
  background-origin: padding-box, border-box;
  background-clip: padding-box, border-box;
  box-shadow: rgba(255,255,255,0.28) 0 1px 0 2px inset, rgba(237,137,54,0.3) 0 2px 6px;
  transition:
    --vbtn-angle 0.4s cubic-bezier(0.25, 0.8, 0.25, 1),
    --vbtn-stop-a 0.35s,
    --vbtn-stop-b 0.35s,
    transform 0.2s cubic-bezier(0.25, 0.8, 0.25, 1),
    box-shadow 0.25s;
  transform: translateZ(0);
}
.pvbtn::before {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: var(--vmc-radius-full, 9999px);
  background: linear-gradient(rgba(255,255,255,0.17) 0%, transparent 55%);
  pointer-events: none;
  z-index: 1;
}
.pvbtn::after {
  content: "";
  position: absolute;
  inset: -4px;
  border-radius: var(--vmc-radius-full, 9999px);
  background: linear-gradient(135deg,
    var(--vmc-color-orange-600, oklch(0.72 0.16 55)),
    var(--vmc-color-vault-500, oklch(0.55 0.22 285))
  );
  filter: blur(14px);
  opacity: 0;
  z-index: -1;
  transition: opacity 0.3s, filter 0.3s;
}
.pvbtn:hover {
  --vbtn-angle: 220deg;
  --vbtn-stop-a: var(--vmc-color-orange-400, #fbc47d);
  --vbtn-stop-b: var(--vmc-color-vault-400, #ae8eff);
  transform: translateY(-2px) scale(1.02);
  box-shadow: rgba(255,255,255,0.22) 0 1px 0 2px inset, rgba(132,96,229,0.35) 0 8px 24px, rgba(237,137,54,0.4) 0 4px 10px;
}
.pvbtn:hover::after { opacity: 0.45; filter: blur(18px); }
.pvbtn:active {
  --vbtn-angle: 135deg;
  --vbtn-stop-a: var(--vmc-color-orange-700, #d46e20);
  --vbtn-stop-b: var(--vmc-color-vault-600, #5a35c2);
  color: #d1d5dc;
  transform: scale(0.97) translateY(1px);
  box-shadow: rgba(0,0,0,0.22) 0 2px 5px 2px inset, rgba(0,0,0,0.12) 0 1px 3px;
}
.pvbtn:active::after { opacity: 0; }
.pvbtn:disabled {
  background-image: none;
  background-color: var(--vmc-color-background-disabled, #e1e3e2);
  color: var(--vmc-color-neutral-700, #99a1af);
  text-shadow: none;
  box-shadow: none;
  cursor: not-allowed;
  transform: none;
  border-color: transparent;
}
.pvbtn:disabled::after { display: none; }
.pvbtn:focus-visible {
  outline: transparent solid 3px;
  outline-offset: 4px;
  transform: scale(0.98);
  box-shadow:
    0 0 0 2px var(--vmc-color-base-white, #fff),
    0 0 0 5px var(--vmc-color-vault-500, oklch(0.55 0.22 285)),
    0 8px 16px -4px rgb(51.76% 37.65% 89.8% / 0.30);
}

/* ── secondary ───────────────────────────────────────────────────────── */
.psec {
  --vsec-stop-a: var(--vmc-color-vault-500, #8460e5);
  --vsec-stop-b: var(--vmc-color-vault-700, #3b1782);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 48px;
  padding: 0 56px;
  border-radius: var(--vmc-radius-full, 9999px);
  /* Borde GRADIENTE lila de Figma (1133:2294): #CFBAFF → white 35% → #AE8EFF 65% → #CFBAFF */
  border: 2px solid transparent;
  cursor: pointer;
  position: relative;
  overflow: hidden;
  font-family: var(--vmc-font-display, "Plus Jakarta Sans", sans-serif);
  font-size: 16px;
  line-height: 20px;
  font-weight: 600;
  color: var(--vmc-color-base-white, #ffffff);
  text-shadow: rgba(0,0,0,0.3) 0 1px 3px;
  background-image:
    linear-gradient(var(--vsec-angle), var(--vsec-stop-a) 0%, var(--vsec-stop-b) 100%),
    linear-gradient(135deg, #cfbaff 0%, #ffffff 35%, #ae8eff 65%, #cfbaff 100%);
  background-origin: padding-box, border-box;
  background-clip: padding-box, border-box;
  box-shadow: rgba(255,255,255,0.22) 0 1px 0 2px inset, rgba(132,96,229,0.3) 0 2px 8px;
  transition:
    --vsec-angle 0.4s cubic-bezier(0.25, 0.8, 0.25, 1),
    --vsec-stop-a 0.35s,
    --vsec-stop-b 0.35s,
    transform 0.2s cubic-bezier(0.25, 0.8, 0.25, 1),
    box-shadow 0.25s;
  transform: translateZ(0);
}
.psec::before {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: var(--vmc-radius-full, 9999px);
  background: linear-gradient(rgba(255,255,255,0.15) 0%, transparent 55%);
  pointer-events: none;
  z-index: 1;
}
.psec::after {
  content: "";
  position: absolute;
  inset: -4px;
  border-radius: var(--vmc-radius-full, 9999px);
  background: linear-gradient(135deg,
    var(--vmc-color-vault-500, oklch(0.55 0.22 285)),
    var(--vmc-color-vault-700, oklch(0.38 0.20 285))
  );
  filter: blur(14px);
  opacity: 0;
  z-index: -1;
  transition: opacity 0.3s, filter 0.3s;
}
.psec:hover {
  --vsec-angle: 219deg;
  --vsec-stop-a: var(--vmc-color-vault-400, #ae8eff);
  --vsec-stop-b: var(--vmc-color-vault-600, #5a35c2);
  transform: translateY(-2px) scale(1.02);
  box-shadow: rgba(255,255,255,0.2) 0 1px 0 2px inset, rgba(132,96,229,0.4) 0 8px 24px, rgba(132,96,229,0.25) 0 4px 10px;
}
.psec:hover::after { opacity: 0.45; filter: blur(18px); }
.psec:active {
  --vsec-angle: 160deg;
  --vsec-stop-a: var(--vmc-color-vault-700, #3b1782);
  --vsec-stop-b: var(--vmc-color-vault-900, #22005c);
  color: #d1d5dc;
  transform: scale(0.97) translateY(1px);
  box-shadow: rgba(0,0,0,0.28) 0 2px 5px 2px inset, rgba(0,0,0,0.14) 0 1px 3px;
}
.psec:active::after { opacity: 0; }
.psec:disabled {
  background-image: none;
  background-color: var(--vmc-color-background-disabled, #e1e3e2);
  color: var(--vmc-color-neutral-700, #99a1af);
  text-shadow: none;
  box-shadow: none;
  cursor: not-allowed;
  transform: none;
  border-color: transparent;
}
.psec:disabled::after { display: none; }
.psec:focus-visible {
  outline: transparent solid 3px;
  outline-offset: 4px;
  transform: scale(0.98);
  box-shadow:
    0 0 0 2px var(--vmc-color-base-white, #fff),
    0 0 0 5px var(--vmc-color-vault-500, oklch(0.55 0.22 285)),
    0 8px 16px -4px rgb(51.76% 37.65% 89.8% / 0.30);
}

/* ── ghost · "Ver Ofertas relacionadas" ─────────────────────────────────
   Sync SVG Figma (1143:1709/1885/1909): frame 215×48 con texto casi al
   borde → padding 12px (antes 28px). Estados ya coincidían exacto. */
.pghost {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 48px;
  padding: 0 12px;
  border-radius: var(--vmc-radius-full, 9999px);
  border: 2px solid rgba(255,255,255,0.75);
  cursor: pointer;
  position: relative;
  overflow: hidden;
  font-family: var(--vmc-font-display, "Plus Jakarta Sans", sans-serif);
  font-size: 16px;
  line-height: 20px;
  font-weight: 600;
  color: var(--vmc-color-base-white, #ffffff);
  background: transparent;
  text-shadow: rgba(0,0,0,0.18) 0 1px 3px;
  box-shadow: rgba(255,255,255,0.2) 0 1px 0 2px inset, rgba(255,255,255,0.15) 0 0 0 1px;
  transition:
    background 0.25s,
    border-color 0.25s,
    color 0.25s,
    transform 0.2s cubic-bezier(0.25, 0.8, 0.25, 1),
    box-shadow 0.25s;
  transform: translateZ(0);
}
.pghost::before {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: var(--vmc-radius-full, 9999px);
  background: linear-gradient(rgba(255,255,255,0.1) 0%, transparent 55%);
  pointer-events: none;
  z-index: 1;
}
.pghost::after {
  content: "";
  position: absolute;
  inset: -4px;
  border-radius: var(--vmc-radius-full, 9999px);
  background: linear-gradient(135deg,
    var(--vmc-color-orange-600, oklch(0.72 0.16 55)),
    var(--vmc-color-vault-500, oklch(0.55 0.22 285))
  );
  filter: blur(16px);
  opacity: 0;
  z-index: -1;
  transition: opacity 0.3s, filter 0.3s;
}
.pghost:hover {
  background: linear-gradient(146.64deg, #fff 0%, rgb(255,240,226) 100%);
  border-color: #fff;
  color: #ed8936;
  text-shadow: rgba(0,0,0,0.25) 0 1px 3px;
  transform: translateY(-2px) scale(1.02);
  box-shadow: rgba(255,255,255,0.5) 0 1px 0 2px inset, rgba(0,0,0,0.2) 0 6px 20px;
}
.pghost:hover::after { opacity: 0.4; filter: blur(18px); }
.pghost:active {
  background: linear-gradient(146.56deg, rgb(212,110,32) 0%, rgb(183,55,0) 100%);
  border-color: #d46e20;
  color: var(--vmc-color-icon-disabled, #e1e3e2);
  text-shadow: rgba(0,0,0,0.25) 0 1px 3px;
  transform: scale(0.97) translateY(1px);
  box-shadow: rgba(0,0,0,0.22) 0 2px 5px 2px inset;
}
.pghost:active::after { opacity: 0; }
.pghost:disabled {
  /* SVG Ghost/Disabled (1153:2443): borde white 0.3, glass white 0.1→transparent, texto white 0.35 */
  background: linear-gradient(rgba(255,255,255,0.1) 0%, transparent 55%);
  border: 2px solid rgba(255,255,255,0.3);
  color: rgba(255,255,255,0.35);
  text-shadow: none;
  box-shadow: none;
  cursor: not-allowed;
  transform: none;
}
.pghost:focus-visible {
  outline: transparent solid 3px;
  outline-offset: 4px;
  transform: scale(0.98);
  box-shadow:
    0 0 0 2px var(--vmc-color-base-white, #fff),
    0 0 0 5px var(--vmc-color-vault-500, oklch(0.55 0.22 285)),
    0 8px 16px -4px rgb(51.76% 37.65% 89.8% / 0.30);
}

/* ── sm-guest ─────────────────────────────────────────────────────────── */
.pvbtn-sm {
  --vbtn-stop-a: var(--vmc-color-orange-600, #ed8936);
  --vbtn-stop-b: var(--vmc-color-vault-500, #8460e5);
  display: inline-flex;
  align-items: center;
  gap: 8px;
  height: 40px;
  min-width: 116px;
  padding: 0 16px 0 4px;
  border-radius: var(--vmc-radius-full, 9999px);
  /* Borde GRADIENTE de Figma (1159:4466): white → #FBC47D 25% → #AE8EFF 75% → white */
  border: 2px solid transparent;
  cursor: pointer;
  position: relative;
  overflow: hidden;
  font-family: var(--vmc-font-display, "Plus Jakarta Sans", sans-serif);
  font-size: 14px;
  line-height: 16px;
  font-weight: 600;
  color: var(--vmc-color-base-white, #ffffff);
  text-shadow: rgba(0,0,0,0.2) 0 1px 2px;
  background-image:
    linear-gradient(var(--vbtn-angle), var(--vbtn-stop-a) 0%, var(--vbtn-stop-a) 40%, var(--vbtn-stop-b) 100%),
    linear-gradient(135deg, #ffffff 0%, #fbc47d 25%, #ae8eff 75%, #ffffff 100%);
  background-origin: padding-box, border-box;
  background-clip: padding-box, border-box;
  box-shadow: rgba(255,255,255,0.25) 0 1px 0 2px inset, rgba(237,137,54,0.25) 0 2px 6px;
  transition:
    --vbtn-angle 0.4s cubic-bezier(0.25, 0.8, 0.25, 1),
    --vbtn-stop-a 0.35s,
    --vbtn-stop-b 0.35s,
    transform 0.2s cubic-bezier(0.25, 0.8, 0.25, 1),
    box-shadow 0.25s;
  transform: translateZ(0);
}
.pvbtn-sm::before {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: var(--vmc-radius-full, 9999px);
  background: linear-gradient(rgba(255,255,255,0.15) 0%, transparent 55%);
  pointer-events: none;
  z-index: 1;
}
.pvbtn-sm:hover {
  --vbtn-angle: 220deg;
  --vbtn-stop-a: var(--vmc-color-orange-400, #fbc47d);
  --vbtn-stop-b: var(--vmc-color-vault-400, #ae8eff);
  transform: translateY(-1px) scale(1.02);
  box-shadow: rgba(255,255,255,0.2) 0 1px 0 2px inset, rgba(132,96,229,0.3) 0 6px 18px, rgba(237,137,54,0.35) 0 3px 8px;
}
.pvbtn-sm:active {
  --vbtn-angle: 135deg;
  --vbtn-stop-a: var(--vmc-color-orange-700, #d46e20);
  --vbtn-stop-b: var(--vmc-color-vault-600, #5a35c2);
  color: #d1d5dc;
  transform: scale(0.97) translateY(1px);
  box-shadow: rgba(0,0,0,0.22) 0 2px 4px 2px inset, rgba(255,255,255,0.28) 0 1px 0 inset, rgba(0,0,0,0.1) 0 1px 2px;
}
.pvbtn-sm:disabled {
  background-image: none;
  background-color: var(--vmc-color-background-disabled, #e1e3e2);
  color: var(--vmc-color-neutral-700, #99a1af);
  text-shadow: none;
  box-shadow: none;
  cursor: not-allowed;
  transform: none;
}
.pvbtn-sm:focus-visible {
  outline: transparent solid 2px;
  outline-offset: 3px;
  box-shadow:
    0 0 0 2px var(--vmc-color-base-white, #fff),
    0 0 0 4px var(--vmc-color-vault-500, oklch(0.55 0.22 285));
}
.pvbtn-icon {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  /* Figma SVG 1159:4466: círculo blanco translúcido (no oscuro) */
  background: rgba(255,255,255,0.2);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  position: relative;
  z-index: 2;
}

/* ── sm-logged-in ─────────────────────────────────────────────────────── */
.pvbtn-auth-d {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  height: 40px;
  padding: 0 16px 0 4px;
  border-radius: var(--vmc-radius-full, 9999px);
  border: 2px solid rgba(255,255,255,0.7);
  cursor: pointer;
  position: relative;
  overflow: hidden;
  font-family: var(--vmc-font-display, "Plus Jakarta Sans", sans-serif);
  font-size: 14px;
  line-height: 16px;
  font-weight: 600;
  color: var(--vmc-color-base-white, #ffffff);
  text-shadow: rgba(0,0,0,0.22) 0 1px 2px;
  background-image: linear-gradient(var(--vbtn-angle), var(--vbtn-stop-a) 0%, var(--vbtn-stop-a) 40%, var(--vbtn-stop-b) 100%);
  box-shadow: rgba(255,255,255,0.28) 0 1px 0 2px inset, rgba(237,137,54,0.3) 0 2px 6px;
  transition:
    --vbtn-angle 0.4s cubic-bezier(0.25, 0.8, 0.25, 1),
    --vbtn-stop-a 0.35s,
    --vbtn-stop-b 0.35s,
    transform 0.2s cubic-bezier(0.25, 0.8, 0.25, 1),
    box-shadow 0.25s;
  transform: translateZ(0);
}
.pvbtn-auth-d:hover {
  --vbtn-angle: 220deg;
  --vbtn-stop-a: var(--vmc-color-orange-400, #fbc47d);
  --vbtn-stop-b: var(--vmc-color-vault-400, #ae8eff);
  transform: translateY(-2px) scale(1.02);
  box-shadow: rgba(255,255,255,0.22) 0 1px 0 2px inset, rgba(132,96,229,0.35) 0 8px 24px, rgba(237,137,54,0.4) 0 4px 10px;
}
.pvbtn-auth-d:active {
  --vbtn-angle: 135deg;
  --vbtn-stop-a: var(--vmc-color-orange-700, #d46e20);
  --vbtn-stop-b: var(--vmc-color-vault-600, #5a35c2);
  color: #d1d5dc;
  transform: scale(0.97) translateY(1px);
  box-shadow: rgba(0,0,0,0.22) 0 2px 5px 2px inset, rgba(0,0,0,0.12) 0 1px 3px;
}
.pvbtn-auth-d:disabled {
  background-image: none;
  background-color: var(--vmc-color-background-disabled, #e1e3e2);
  color: var(--vmc-color-neutral-700, #99a1af);
  text-shadow: none;
  box-shadow: none;
  cursor: not-allowed;
  transform: none;
}
.pvbtn-auth-d:focus-visible {
  outline: transparent solid 3px;
  outline-offset: 4px;
  transform: scale(0.98);
  box-shadow:
    0 0 0 2px var(--vmc-color-base-white, #fff),
    0 0 0 5px var(--vmc-color-vault-500, oklch(0.55 0.22 285)),
    0 8px 16px -4px rgb(51.76% 37.65% 89.8% / 0.30);
}
.pvbtn-auth-d-icon {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: rgba(0,0,0,0.18);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  position: relative;
  z-index: 2;
}
.pvbtn-auth-d-username {
  font-weight: 700;
  opacity: 0.92;
}

/* ── prefers-reduced-motion ──────────────────────────────────────────── */
/* ── negotiable (teal → vault) · sync EXACTO del SVG export de Figma ────
   Nodos 1807:14907/14943/14957 · 200×48 FIJO · borde gradiente teal→vault
   Spec: .claude/concorde/inbox/figma-ButtonNegotiable-svg-export.json */
.pneg {
  --vneg-stop-a: var(--vmc-color-teal-500, #00aeb1);
  --vneg-stop-b: var(--vmc-color-vault-500, #8460e5);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 48px;
  min-width: 200px;
  padding: 0 24px;
  border-radius: var(--vmc-radius-full, 9999px);
  /* Borde GRADIENTE de Figma (no blanco sólido): capa border-box bajo el fill */
  border: 2px solid transparent;
  cursor: pointer;
  position: relative;
  overflow: hidden;
  font-family: var(--vmc-font-display, "Plus Jakarta Sans", sans-serif);
  font-size: 16px;
  line-height: 20px;
  font-weight: 600;
  color: var(--vmc-color-base-white, #ffffff);
  text-shadow: rgba(0,0,0,0.25) 0 1px 3px;
  background-image:
    linear-gradient(var(--vneg-angle), var(--vneg-stop-a) 0%, var(--vneg-stop-a) 40%, var(--vneg-stop-b) 100%),
    linear-gradient(135deg, #ffffff 0%, #4ddcdc 25%, #6445df 75%, #ffffff 100%);
  background-origin: padding-box, border-box;
  background-clip: padding-box, border-box;
  box-shadow: rgba(255,255,255,0.28) 0 1px 0 2px inset, rgba(0,174,177,0.35) 0 2px 6px;
  transition:
    --vneg-angle 0.4s cubic-bezier(0.25, 0.8, 0.25, 1),
    --vneg-stop-a 0.35s,
    --vneg-stop-b 0.35s,
    transform 0.2s cubic-bezier(0.25, 0.8, 0.25, 1),
    box-shadow 0.25s;
  transform: translateZ(0);
}
.pneg::before {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: var(--vmc-radius-full, 9999px);
  background: linear-gradient(rgba(255,255,255,0.17) 0%, transparent 55%);
  pointer-events: none;
  z-index: 1;
}
.pneg::after {
  content: "";
  position: absolute;
  inset: -4px;
  border-radius: var(--vmc-radius-full, 9999px);
  background: linear-gradient(135deg,
    var(--vmc-color-teal-500, #00aeb1),
    var(--vmc-color-vault-500, #8460e5)
  );
  filter: blur(14px);
  opacity: 0;
  z-index: -1;
  transition: opacity 0.3s, filter 0.3s;
}
.pneg:hover {
  --vneg-angle: 220deg;
  --vneg-stop-a: var(--vmc-color-teal-400, #00cccc);
  --vneg-stop-b: var(--vmc-color-vault-400, #ae8eff);
  transform: translateY(-2px) scale(1.02);
  /* Sombras exactas del SVG hover: teal cercana + glow púrpura #6445DF */
  box-shadow: rgba(255,255,255,0.22) 0 1px 0 2px inset, rgba(0,174,177,0.4) 0 4px 10px, rgba(100,69,223,0.35) 0 8px 24px;
}
.pneg:hover::after { opacity: 0.45; filter: blur(18px); }
.pneg:active {
  --vneg-angle: 135deg;
  --vneg-stop-a: var(--vmc-color-teal-600, #009095);
  --vneg-stop-b: var(--vmc-color-vault-600, #5a35c2);
  color: #d1d5dc; /* exacto del SVG pressed */
  transform: scale(0.97) translateY(1px);
  box-shadow: rgba(0,0,0,0.22) 0 2px 5px 2px inset, rgba(0,0,0,0.12) 0 1px 3px;
}
.pneg:active::after { opacity: 0; }
.pneg:disabled {
  background-image: none;
  background-color: var(--vmc-color-background-disabled, #e1e3e2);
  color: var(--vmc-color-neutral-700, #99a1af);
  text-shadow: none;
  box-shadow: none;
  cursor: not-allowed;
  transform: none;
  border-color: transparent;
}
.pneg:disabled::after { display: none; }
.pneg:focus-visible {
  outline: transparent solid 3px;
  outline-offset: 4px;
  transform: scale(0.98);
  box-shadow:
    0 0 0 2px var(--vmc-color-base-white, #fff),
    0 0 0 5px var(--vmc-color-teal-500, #00aeb1),
    0 8px 16px -4px rgba(0,174,177,0.3);
}

/* ── outline · "Regístrate" — RECONSTRUIDO desde cero con SVGs de Figma ──
   Default 1932:10613 · Hover 1934:10627 · Pressed 1935:10631 (215×48, radius full)
   3 capas Figma por estado: relleno (paint0) + borde 1px gradiente (stroke) + glass white 0.1 (paint2)
   Borde = STROKE de 1px (sin stroke-width = 1px), NO 2px. Glass presente en TODOS los estados. */
.poutline {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 48px;
  padding: 0 56px;
  border-radius: var(--vmc-radius-full, 9999px);
  border: none;
  cursor: pointer;
  position: relative;
  font-family: var(--vmc-font-display, "Plus Jakarta Sans", sans-serif);
  font-size: 16px;
  line-height: 20px;
  font-weight: 600;
  color: var(--vmc-color-orange-600, #ed8936);
  /* Default: relleno transparente + glass white 0.1 → transparent 55% (paint1) */
  background-image: linear-gradient(180deg, rgba(255,255,255,0.1) 0%, rgba(255,255,255,0) 55%);
  box-shadow: none;
  transition:
    background 0.25s,
    color 0.25s,
    transform 0.2s cubic-bezier(0.25, 0.8, 0.25, 1),
    box-shadow 0.25s;
  transform: translateZ(0);
}
/* Borde = anillo gradiente de 1px (centro 100% transparente, sin doble borde) — mask trick.
   Default/Hover: naranja diagonal #FF9639 → #EF852E 50% → #BE3D00 (vector ~144deg) */
.poutline::before {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: inherit;
  padding: 1px;
  background: linear-gradient(144deg, #ff9639 0%, #ef852e 50%, #be3d00 100%);
  -webkit-mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
  -webkit-mask-composite: xor;
  mask-composite: exclude;
  pointer-events: none;
  z-index: 1;
  transition: background 0.25s;
}
/* Glow exterior — interacción Concorde (no existe en Figma estático) */
.poutline::after {
  content: "";
  position: absolute;
  inset: -4px;
  border-radius: inherit;
  background: linear-gradient(144deg,
    var(--vmc-color-orange-600, #ed8936),
    var(--vmc-color-orange-tint, #fff0e2)
  );
  filter: blur(16px);
  opacity: 0;
  z-index: -1;
  transition: opacity 0.3s, filter 0.3s;
}
.poutline:hover {
  /* Hover 1934:10627: relleno white→#FFF0E2 horizontal (paint0) + glass (paint2). Un solo borde 1px */
  background-image:
    linear-gradient(180deg, rgba(255,255,255,0.1) 0%, rgba(255,255,255,0) 55%),
    linear-gradient(90deg, #ffffff 0%, var(--vmc-color-orange-tint, #fff0e2) 100%);
  color: var(--vmc-color-orange-600, #ed8936);
  text-shadow: rgba(0,0,0,0.08) 0 1px 2px;
  transform: translateY(-2px) scale(1.02);
  box-shadow: rgba(190,61,0,0.18) 0 6px 18px -4px;
}
.poutline:hover::after { opacity: 0.35; filter: blur(18px); }
.poutline:active {
  /* Pressed 1935:10631: relleno #D46E20→#B73700 (paint0 ~156deg) + glass. Borde oscuro vertical */
  background-image:
    linear-gradient(180deg, rgba(255,255,255,0.1) 0%, rgba(255,255,255,0) 55%),
    linear-gradient(156deg, #d46e20 0%, #b73700 100%);
  color: var(--vmc-color-base-white, #fff);
  text-shadow: rgba(0,0,0,0.22) 0 1px 2px;
  transform: scale(0.97) translateY(1px);
  box-shadow: rgba(0,0,0,0.16) 0 1px 3px;
}
/* Pressed: anillo oscuro #B25614 → #93420A VERTICAL (paint1 vector 180deg) */
.poutline:active::before { background: linear-gradient(180deg, #b25614 0%, #93420a 100%); }
.poutline:active::after { opacity: 0; }
.poutline:disabled {
  background-image: linear-gradient(180deg, rgba(255,255,255,0.1) 0%, rgba(255,255,255,0) 55%);
  color: rgba(237,137,54,0.4);
  box-shadow: none;
  cursor: not-allowed;
  transform: none;
}
.poutline:disabled::before { background: rgba(237,137,54,0.3); }
.poutline:disabled::after { opacity: 0; }
.poutline:focus-visible {
  outline: transparent solid 3px;
  outline-offset: 4px;
  transform: scale(0.98);
  box-shadow:
    0 0 0 2px var(--vmc-color-base-white, #fff),
    0 0 0 5px var(--vmc-color-orange-600, #ed8936);
}

/* ── secondary-sm · "Agenda tu visita" ──────────────────────────────────
   Sync EXACTO del SVG export de Figma (Variant=Secondary, Size=Small)
   Nodos 1442:10976 / 1464:19933 / 1464:20511 · 160×40 fijo · ícono calendario
   Spec: .claude/concorde/inbox/figma-ButtonGhost-SecondarySm-svg-export.json */
.psec-sm {
  --vss-stop-a: var(--vmc-color-vault-500, #8460e5);
  --vss-stop-b: var(--vmc-color-vault-700, #3b1782);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  height: 40px;
  min-width: 160px;
  padding: 0 12px 0 4px;
  border-radius: var(--vmc-radius-full, 9999px);
  /* Borde GRADIENTE lila de Figma (constante en los 3 estados) */
  border: 2px solid transparent;
  cursor: pointer;
  position: relative;
  overflow: hidden;
  font-family: var(--vmc-font-display, "Plus Jakarta Sans", sans-serif);
  font-size: 14px;
  line-height: 16px;
  font-weight: 600;
  color: var(--vmc-color-base-white, #ffffff);
  text-shadow: rgba(0,0,0,0.25) 0 1px 3px;
  background-image:
    linear-gradient(var(--vss-angle), var(--vss-stop-a) 0%, var(--vss-stop-b) 100%),
    linear-gradient(135deg, #cfbaff 0%, #ffffff 35%, #ae8eff 65%, #cfbaff 100%);
  background-origin: padding-box, border-box;
  background-clip: padding-box, border-box;
  box-shadow: rgba(255,255,255,0.22) 0 1px 0 2px inset, rgba(132,96,229,0.3) 0 2px 8px;
  transition:
    --vss-angle 0.4s cubic-bezier(0.25, 0.8, 0.25, 1),
    --vss-stop-a 0.35s,
    --vss-stop-b 0.35s,
    transform 0.2s cubic-bezier(0.25, 0.8, 0.25, 1),
    box-shadow 0.25s;
  transform: translateZ(0);
}
.psec-sm::before {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: var(--vmc-radius-full, 9999px);
  background: linear-gradient(rgba(255,255,255,0.16) 0%, transparent 55%);
  pointer-events: none;
  z-index: 1;
}
.psec-sm:hover {
  --vss-angle: 219deg;
  --vss-stop-a: var(--vmc-color-vault-400, #ae8eff);
  --vss-stop-b: var(--vmc-color-vault-600, #5a35c2);
  transform: translateY(-1px) scale(1.02);
  box-shadow: rgba(255,255,255,0.2) 0 1px 0 2px inset, rgba(132,96,229,0.25) 0 4px 10px, rgba(132,96,229,0.4) 0 8px 24px;
}
.psec-sm:active {
  --vss-angle: 160deg;
  --vss-stop-a: var(--vmc-color-vault-700, #3b1782);
  --vss-stop-b: var(--vmc-color-vault-900, #22005c);
  color: #d1d5dc;
  transform: scale(0.97) translateY(1px);
  box-shadow: rgba(0,0,0,0.28) 0 2px 5px 2px inset, rgba(0,0,0,0.14) 0 1px 3px;
}
.psec-sm:disabled {
  background-image: none;
  background-color: var(--vmc-color-background-disabled, #e1e3e2);
  color: var(--vmc-color-neutral-700, #99a1af);
  text-shadow: none;
  box-shadow: none;
  cursor: not-allowed;
  transform: none;
  border-color: transparent;
}
.psec-sm:focus-visible {
  outline: transparent solid 2px;
  outline-offset: 3px;
  box-shadow:
    0 0 0 2px var(--vmc-color-base-white, #fff),
    0 0 0 4px var(--vmc-color-vault-500, #8460e5);
}
.psec-sm-icon {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: rgba(255,255,255,0.2);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  position: relative;
  z-index: 2;
}

/* ── prefers-reduced-motion ──────────────────────────────────────────── */
@media (prefers-reduced-motion: reduce) {
  .pvbtn, .psec, .psec-sm, .pneg, .pghost, .poutline, .pvbtn-sm, .pvbtn-auth-d {
    transition: none;
  }
  .pvbtn::after, .psec::after, .pneg::after, .pghost::after, .poutline::after {
    transition: none;
  }
}
`;

// ── Style injection ───────────────────────────────────────────────────────

const STYLE_ID = "concorde-button-styles";
let stylesInjected = false;

function injectStyles(): void {
  if (typeof document === "undefined" || stylesInjected) return;
  if (!document.getElementById(STYLE_ID)) {
    const el = document.createElement("style");
    el.id = STYLE_ID;
    el.textContent = BUTTON_STYLES;
    document.head.appendChild(el);
  }
  stylesInjected = true;
}

// ── Icon ─────────────────────────────────────────────────────────────────

// Ícono "user" — path EXACTO del SVG export de Figma (Primary/Small "Ingresa",
// nodo 1159:4466). Cabeza circular + cuerpo (hombros) rellenos. 24px dentro del
// círculo de 32px (igual que Figma). fill=currentColor → en pressed hereda #E1E3E2.
export function UserIcon(): JSX.Element {
  return (
    <svg
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="currentColor"
      aria-hidden="true"
    >
      <path d="M15.5412 7.36C15.5412 5.52 13.9765 4 12 4C10.0235 4 8.5412 5.52 8.5412 7.36C8.5412 9.28 10.0235 10.8 12 10.8C13.9765 10.8 15.5412 9.28 15.5412 7.36ZM5 16.4C6.4824 18.56 9.1176 20 12 20C14.8824 20 17.5176 18.56 19 16.4C19 14.16 14.3059 12.88 12 12.88C9.6941 12.88 5 14.16 5 16.4Z" />
    </svg>
  );
}

// Ícono calendario — paths EXACTOS del SVG de Figma (Secondary/Small "Agenda tu visita").
// stroke currentColor → en pressed hereda #e1e3e2 igual que en Figma.
export function CalendarIcon(): JSX.Element {
  return (
    <svg
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <rect x="6" y="7" width="12" height="11" rx="2" />
      <path d="M6 11h12" />
      <path d="M9 5.5v3" />
      <path d="M15 5.5v3" />
    </svg>
  );
}

// ── Variant → class map ───────────────────────────────────────────────────

const VARIANT_CLASS: Record<ButtonVariant, string> = {
  primary: "pvbtn",
  negotiable: "pneg",
  secondary: "psec",
  "secondary-sm": "psec-sm",
  ghost: "pghost",
  outline: "poutline",
  "sm-guest": "pvbtn-sm",
  "sm-logged-in": "pvbtn-auth-d",
};

// ── Component ─────────────────────────────────────────────────────────────

const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "primary", icon, username, className, type = "button", children, ...rest },
  ref,
) {
  injectStyles();

  const cls = VARIANT_CLASS[variant];

  let content: ReactNode;
  if (variant === "sm-guest") {
    content = (
      <>
        {icon ? <span className="pvbtn-icon">{icon}</span> : null}
        {children}
      </>
    );
  } else if (variant === "secondary-sm") {
    content = (
      <>
        {icon ? <span className="psec-sm-icon">{icon}</span> : null}
        {children}
      </>
    );
  } else if (variant === "sm-logged-in") {
    content = (
      <>
        {icon ? <span className="pvbtn-auth-d-icon">{icon}</span> : null}
        Bienvenido,{" "}
        <span className="pvbtn-auth-d-username">{username ?? children}</span>
      </>
    );
  } else {
    content = children;
  }

  return (
    <>
      <style
        id={`${STYLE_ID}-ssr`}
        suppressHydrationWarning
        dangerouslySetInnerHTML={{ __html: BUTTON_STYLES }}
      />
      <button
        ref={ref}
        className={[cls, className].filter(Boolean).join(" ")}
        type={type}
        {...rest}
      >
        {content}
      </button>
    </>
  );
});

export default Button;
