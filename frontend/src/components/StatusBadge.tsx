import type { ConversationStatus } from "@/lib/types";
import { STATUS_LABEL } from "@/lib/format";

/**
 * Pill de estado de conversación (RF-009/RF-032). Mismo lenguaje visual que
 * BadgeStatus de Concorde (pill uppercase + dot), pero con las 4 variantes propias
 * del dominio de Subastín en vez de las de subasta (EN VIVO/PRÓXIMA) — por eso vive
 * como componente propio y no como edición del original.
 */

const DOT_COLOR: Record<ConversationStatus, string> = {
  BOT_ATTENDING: "#8460E5",
  PENDING_ADVISOR: "#ED8936",
  IN_ATTENTION: "#00AEB1",
  CLOSED: "#99A1AF",
};

const BG: Record<ConversationStatus, string> = {
  BOT_ATTENDING: "#F1EDFD",
  PENDING_ADVISOR: "#FDF0E4",
  IN_ATTENTION: "#E3F8F8",
  CLOSED: "#EEEEEE",
};

const TEXT: Record<ConversationStatus, string> = {
  BOT_ATTENDING: "#3B1782",
  PENDING_ADVISOR: "#9A4A0F",
  IN_ATTENTION: "#00696B",
  CLOSED: "#5C6266",
};

export default function StatusBadge({ status }: { status: ConversationStatus }) {
  return (
    <span
      className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-1 text-[11px] font-bold uppercase tracking-wide"
      style={{ background: BG[status], color: TEXT[status] }}
    >
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: DOT_COLOR[status] }} />
      {STATUS_LABEL[status]}
    </span>
  );
}
