/**
 * StatusTag — etiqueta de estado de una fila de Mi Garaje (mi-garaje-lab · Garaje, antes «Status»).
 * Píldora de texto con color por tono; el tono «live» usa BadgeStatus (EN VIVO), como el resto de Concorde.
 * Depende de React y BadgeStatus.
 */
import type { JSX, ReactNode } from "react";
import BadgeStatus from "@/concorde/components/BadgeStatus";

/** Tonos que muestra Mi Garaje: en vivo (filas de Tu actividad), en espera y en revisión (Mis valorizaciones). */
export type StatusTone = "live" | "wait" | "progress";

export const STATUS_TAG_CSS = String.raw`
.g-status { display:inline-flex; align-items:center; height:24px; padding:0 10px; border-radius:9999px; font-size:.75rem; font-weight:700; white-space:nowrap; }
.g-status--progress { color:#5A35C2; background:#F5F0FF; }
.g-status--wait { color:color-mix(in srgb,#191C1C 82%,#fff); background:color-mix(in srgb,#E1E3E2 60%,#fff); }
`;

export interface StatusTagProps {
  /** Tono: «live» muestra el BadgeStatus EN VIVO; «wait» (gris) y «progress» (violeta) son píldoras de texto. */
  tone: StatusTone;
  /** Texto del estado (p. ej. «Publicada», «Pendiente de aprobación»). */
  children: ReactNode;
}

export function StatusTag({ tone, children }: StatusTagProps): JSX.Element {
  if (tone === "live") return <BadgeStatus variant="live" label="EN VIVO" />;
  return <>
    <style href="concorde-status-tag" precedence="default">{STATUS_TAG_CSS}</style>
    <span className={`g-status g-status--${tone}`}>{children}</span>
  </>;
}

export default StatusTag;
