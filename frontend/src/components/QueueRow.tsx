import Link from "next/link";
import AvatarZone from "@/concorde/components/AvatarZone";
import { formatWaitTime, STATUS_LABEL } from "@/lib/format";
import type { Conversation, ConversationStatus } from "@/lib/types";

const URGENCY_COLOR: Record<ConversationStatus, string> = {
  PENDING_ADVISOR: "#ED8936",
  IN_ATTENTION: "#00AEB1",
  BOT_ATTENDING: "#8460E5",
  CLOSED: "#C7C9CC",
};

/**
 * `closed_by` solo distingue ADVISOR de todo lo demás (D-029): "AUTO" y `null`/`undefined`
 * (conversaciones cerradas antes de que el campo existiera) caen a "Subastín" — ningún otro
 * actor cierra una conversación hoy. Mismos colores que el dot de estado (morado = bot, verde
 * azulado = asesor) para que la cola no invente una tercera paleta. Panel de KAMs: "asesor",
 * no "humano" — la palabra suena a etiqueta de laboratorio, no a quién los usa.
 */
function closedByTag(closedBy: Conversation["closed_by"]): { label: string; color: string } {
  return closedBy === "ADVISOR"
    ? { label: "Cerrado por asesor", color: URGENCY_COLOR.IN_ATTENTION }
    : { label: "Cerrado por Subastín", color: URGENCY_COLOR.BOT_ATTENDING };
}

/**
 * Fila compacta de la cola del cockpit (RF-029/RF-032 condensados). Tomar un
 * caso pasa por abrir el hilo, no por esta fila — la fila solo triage.
 */
export default function QueueRow({
  conversation,
  active,
  mostUrgent = false,
  now,
  isMine,
}: {
  conversation: Conversation;
  active: boolean;
  /** El caso pendiente que más tiempo lleva esperando sin tomar — se resalta para que sea el punto de partida obvio. */
  mostUrgent?: boolean;
  now: number;
  isMine: boolean;
}) {
  return (
    <Link
      href={`/advisor/inbox/${conversation.conversation_id}`}
      aria-current={active ? "page" : undefined}
      className={`flex items-start gap-3 px-3 py-2.5 transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--vmc-color-vault-500)] ${
        active
          ? "bg-[color:var(--vmc-color-vault-500)]/10"
          : mostUrgent
            ? "bg-[color:var(--vmc-color-orange-600)]/5 hover:bg-[color:var(--vmc-color-orange-600)]/10"
            : "hover:bg-neutral-50"
      }`}
    >
      <span
        className="mt-2 h-2 w-2 flex-shrink-0 rounded-full"
        style={{ background: URGENCY_COLOR[conversation.status] }}
        aria-hidden
      />
      <AvatarZone size="sm" title={conversation.user_name ?? "Anónimo"} />
      <span className="min-w-0 flex-1">
        <span className="flex items-center justify-between gap-2">
          <span className="truncate text-sm font-semibold text-[#191C1C]">
            {conversation.user_name ?? "Anónimo"}
          </span>
          <span className="flex-shrink-0 text-[11px] text-neutral-500">
            {formatWaitTime(conversation.last_message_at, now)}
          </span>
        </span>
        <span className="mt-0.5 line-clamp-1 block text-xs text-neutral-500">
          {conversation.last_message_preview}
        </span>
        <span className="mt-1 flex items-center gap-1.5 text-[11px] font-medium text-neutral-400">
          {mostUrgent ? (
            <span className="font-bold text-[#9A4A0F]">Más urgente</span>
          ) : conversation.status === "CLOSED" ? (
            (() => {
              const tag = closedByTag(conversation.closed_by);
              return (
                <span
                  className="rounded-full px-1.5 py-0.5 text-[10px] font-bold"
                  style={{ background: `${tag.color}1A`, color: tag.color }}
                >
                  {tag.label}
                </span>
              );
            })()
          ) : (
            isMine ? "Tú" : STATUS_LABEL[conversation.status]
          )}
          {conversation.unread_count > 0 && (
            <span className="rounded-full bg-[color:var(--vmc-color-orange-600)] px-1.5 py-0.5 text-[10px] font-bold text-white">
              {conversation.unread_count}
            </span>
          )}
        </span>
      </span>
    </Link>
  );
}
