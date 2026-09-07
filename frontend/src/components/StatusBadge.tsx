import type { ConversationStatus } from "@/lib/types";
import { STATUS_LABEL } from "@/lib/format";
import { STATUS_BG, STATUS_COLOR, STATUS_DEEP_COLOR } from "@/lib/status-colors";

/**
 * Pill de estado de conversación (RF-009/RF-032). Mismo lenguaje visual que
 * BadgeStatus de Concorde (pill uppercase + dot), pero con las 4 variantes propias
 * del dominio de Subastín en vez de las de subasta (EN VIVO/PRÓXIMA) — por eso vive
 * como componente propio y no como edición del original. Los colores viven en
 * `lib/status-colors.ts`, compartidos con la cola y el dashboard.
 */
export default function StatusBadge({ status }: { status: ConversationStatus }) {
  return (
    <span
      className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-1 text-[11px] font-bold uppercase tracking-wide"
      style={{ background: STATUS_BG[status], color: STATUS_DEEP_COLOR[status] }}
    >
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: STATUS_COLOR[status] }} />
      {STATUS_LABEL[status]}
    </span>
  );
}
