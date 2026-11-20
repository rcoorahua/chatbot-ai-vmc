"use client";

/**
 * BadgeStatus — Generado por Concorde
 * Fuente: https://voyager-ds.vercel.app/preview/components/pase1
 * Generado: 2026-05-28
 *
 * Pill badge de estado de subasta: EN VIVO (animated dot) · PRÓXIMA (blinking clock)
 */

import type { JSX } from "react";

// ─── Types ────────────────────────────────────────────────────────────────────

export type BadgeStatusVariant = "live" | "proxima";

export interface BadgeStatusProps {
  variant: BadgeStatusVariant;
  /** Override de label / contenido editable (default: "EN VIVO" / "PRÓXIMA") */
  label?: string;
  /** Muestra el dot (live) / reloj (proxima). false = solo el texto. Default true. */
  icon?: boolean;
  className?: string;
}

// ─── Self-contained CSS ───────────────────────────────────────────────────────

const STYLE_ID = "concorde-badgestatus-styles";

const BADGESTATUS_STYLES = `
/* Pulso del punto EN VIVO — frames exactos del SVG: On (6px, opacidad 1) ↔ On-1 (4px, 0.28) */
@keyframes badgestatus-live-pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50%      { opacity: 0.28; transform: scale(0.67); }
}

/* Parpadeo del reloj PRÓXIMA — On (sólido) ↔ Off (0.28) */
@keyframes badgestatus-clock-blink {
  0%, 100% { opacity: 1; transform: scale(1); }
  50%      { opacity: 0.28; transform: scale(0.85); }
}

/* ── Base pill ── */
.badgestatus {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  padding: 3px 8px 3px 6px;
  min-width: 80px; /* EN VIVO y PRÓXIMA con el mismo ancho al apilarse */
  box-sizing: border-box;
  border-radius: 9999px;
  font-family: var(--vmc-font-display, 'Plus Jakarta Sans', system-ui, sans-serif);
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.07em;
  text-transform: uppercase;
  white-space: nowrap;
  backdrop-filter: blur(6px);
  -webkit-backdrop-filter: blur(6px);
  color: oklch(1 0 0);
  border: 1px solid transparent;
  user-select: none;
}

/* ── EN VIVO — sync EXACTO SVG (1310:11895 / 11904) ──
   bg naranja diagonal + borde gradiente cálido + ring naranja */
.badgestatus--live {
  background-image:
    linear-gradient(135deg, #f4ac59 0%, #ed8936 40%, #b25614 100%),
    linear-gradient(135deg, #fbc47d 0%, rgba(255,255,255,0.45) 40%, #d46e20 75%, #fbc47d 100%);
  background-origin: padding-box, border-box;
  background-clip: padding-box, border-box;
  box-shadow:
    rgba(237, 137, 54, 0.45) 0px 2px 10px,
    rgba(255, 255, 255, 0.14) 0px 1px 0px inset;
}

/* ── PRÓXIMA — sync EXACTO SVG (1310:11797 / 11799) ──
   bg morado diagonal + borde gradiente lila + glow morado #22005c */
.badgestatus--proxima {
  background-image:
    linear-gradient(135deg, #8460e5 0%, #3b1782 100%),
    linear-gradient(135deg, #ae8eff 0%, rgba(255,255,255,0.4) 38%, #5a35c2 68%, #ae8eff 100%);
  background-origin: padding-box, border-box;
  background-clip: padding-box, border-box;
  box-shadow:
    rgba(34, 0, 92, 0.5) 0px 2px 10px,
    rgba(255, 255, 255, 0.1) 0px 1px 0px inset;
}

/* ── Pulsing dot (live) ── */
.badgestatus-dot {
  width: 6px;
  height: 6px;
  border-radius: 9999px;
  background: #ffffff;
  flex-shrink: 0;
  animation: badgestatus-live-pulse 1.4s ease-in-out infinite;
  position: relative;
}

/* ── Blinking clock (proxima) ── */
.badgestatus-clock {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  animation: badgestatus-clock-blink 1.4s ease-in-out infinite;
}

/* ── Reduced motion ── */
@media (prefers-reduced-motion: reduce) {
  .badgestatus-dot   { animation: none; }
  .badgestatus-clock { animation: none; }
}
`;

let _stylesInjected = false;

// ─── Clock SVG (Próxima) ──────────────────────────────────────────────────────

function ClockIcon(): JSX.Element {
  return (
    <svg
      width="10"
      height="10"
      viewBox="0 0 24 24"
      fill="none"
      stroke="rgba(255,255,255,0.92)"
      strokeWidth="2.2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <circle cx="12" cy="12" r="10" />
      <polyline points="12 6 12 12 16 14" />
    </svg>
  );
}

// ─── Component ────────────────────────────────────────────────────────────────

const LABEL_DEFAULTS: Record<BadgeStatusVariant, string> = {
  live:    "EN VIVO",
  proxima: "PRÓXIMA",
};

export default function BadgeStatus({
  variant,
  label,
  icon = true,
  className = "",
}: BadgeStatusProps): JSX.Element {
  if (typeof document !== "undefined" && !_stylesInjected) {
    if (!document.getElementById(STYLE_ID)) {
      const el = document.createElement("style");
      el.id = STYLE_ID;
      el.textContent = BADGESTATUS_STYLES;
      document.head.appendChild(el);
    }
    _stylesInjected = true;
  }

  const displayLabel = label ?? LABEL_DEFAULTS[variant];

  const classes = [
    "badgestatus",
    `badgestatus--${variant}`,
    className,
  ].filter(Boolean).join(" ");

  return (
    <>
      <style
        id={`${STYLE_ID}-ssr`}
        suppressHydrationWarning
        dangerouslySetInnerHTML={{ __html: BADGESTATUS_STYLES }}
      />
      <span
        className={classes}
        role="status"
        aria-label={displayLabel}
      >
        {icon && variant === "live" ? (
          <span className="badgestatus-dot" aria-hidden="true" />
        ) : null}
        {icon && variant === "proxima" ? (
          <span className="badgestatus-clock" aria-hidden="true">
            <ClockIcon />
          </span>
        ) : null}
        <span>{displayLabel}</span>
      </span>
    </>
  );
}
