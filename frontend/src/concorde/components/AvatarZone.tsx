"use client";

/**
 * AvatarZone — Generado por Concorde
 * Fuente: Figma VOYAGER · "Avatar Zone" (nodo 2035:16583)
 *
 * Avatar circular 32×32: relleno gradiente naranja (#FF9639 → #EF852E → #BE3D00)
 * con silueta de persona blanca centrada. Tamaño personalizable:
 * "sm" (24px) · "md" (32px) · o número de px.
 */

import { useId } from "react";
import type { JSX } from "react";

// ─── Types ────────────────────────────────────────────────────────────────────

export type AvatarZoneSize = "sm" | "md";

export interface AvatarZoneProps {
  /** Tamaño: "sm"=24px · "md"=32px · o número de px (default "md") */
  size?: AvatarZoneSize | number;
  /** Texto accesible — si se omite, el avatar es decorativo (aria-hidden) */
  title?: string;
  className?: string;
}

const SIZE_PX: Record<AvatarZoneSize, number> = { sm: 24, md: 32 };

const CIRCLE_PATH =
  "M0 16C0 7.16344 7.16344 0 16 0C24.8366 0 32 7.16344 32 16C32 24.8366 24.8366 32 16 32C7.16344 32 0 24.8366 0 16Z";

// ─── Component ────────────────────────────────────────────────────────────────

export default function AvatarZone({ size = "md", title, className = "" }: AvatarZoneProps): JSX.Element {
  const uid = useId().replace(/:/g, "-");
  const px = typeof size === "number" ? size : SIZE_PX[size];

  return (
    <svg
      width={px}
      height={px}
      viewBox="0 0 32 32"
      fill="none"
      className={className}
      role={title ? "img" : undefined}
      aria-hidden={title ? undefined : true}
      aria-label={title}
    >
      {title ? <title>{title}</title> : null}
      <g clipPath={`url(#${uid}-c0)`}>
        <path d={CIRCLE_PATH} fill={`url(#${uid}-bg)`} />
        <g clipPath={`url(#${uid}-c1)`}>
          <path
            d="M19.5412 11.36C19.5412 9.52 17.9765 8 16 8C14.0235 8 12.5412 9.52 12.5412 11.36C12.5412 13.28 14.0235 14.8 16 14.8C17.9765 14.8 19.5412 13.28 19.5412 11.36ZM9 20.4C10.4824 22.56 13.1176 24 16 24C18.8824 24 21.5176 22.56 23 20.4C23 18.16 18.3059 16.88 16 16.88C13.6941 16.88 9 18.16 9 20.4Z"
            fill="white"
          />
        </g>
      </g>
      <defs>
        <linearGradient id={`${uid}-bg`} x1="5.42742" y1="-16.8777" x2="43.7544" y2="-4.5528" gradientUnits="userSpaceOnUse">
          <stop stopColor="#FF9639" />
          <stop offset="0.5" stopColor="#EF852E" />
          <stop offset="1" stopColor="#BE3D00" />
        </linearGradient>
        <clipPath id={`${uid}-c0`}>
          <path d={CIRCLE_PATH} fill="white" />
        </clipPath>
        <clipPath id={`${uid}-c1`}>
          <rect width="24" height="24" fill="white" transform="translate(4 4)" />
        </clipPath>
      </defs>
    </svg>
  );
}
