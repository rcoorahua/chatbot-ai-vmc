import type { ConversationStatus, SenderType } from "./types";

/** T7: los estados viven en inglés en el backend; el texto visible vive solo en el frontend. */
export const STATUS_LABEL: Record<ConversationStatus, string> = {
  BOT_ATTENDING: "Bot atendiendo",
  PENDING_ADVISOR: "Pendiente asesor",
  IN_ATTENTION: "En atención",
  CLOSED: "Cerrada",
};

export const SENDER_LABEL: Record<SenderType, string> = {
  USER: "Usuario",
  BOT: "Subastín",
  ADVISOR: "Asesor",
  SYSTEM: "Sistema",
};

/** Traduce el código SystemEvent (RF-050) que viaja como contenido de un mensaje SYSTEM. */
export const SYSTEM_EVENT_LABEL: Record<string, string> = {
  HANDOFF_REQUESTED: "Se solicitó un asesor",
  ADVISOR_ASSIGNED: "Un asesor tomó la conversación",
  TICKET_OPENED: "Ticket abierto",
  TICKET_CLOSED: "Ticket cerrado",
  BOT_DISABLED: "El bot dejó de responder",
  BOT_ENABLED: "El bot volvió a responder",
  CONVERSATION_CLOSED: "Conversación finalizada",
};

/**
 * "Ahora" fijo para el mock (en vez de Date.now(), impuro y con reglas de purity de React
 * en contra de calcularlo en render/efecto). Los timestamps de mock-data.ts son anteriores
 * a este instante para que los tiempos de espera se vean creíbles.
 */
export const MOCK_NOW_MS = new Date("2026-08-27T14:20:00Z").getTime();

export function formatWaitTime(fromIso: string, nowMs: number): string {
  const minutes = Math.max(0, Math.round((nowMs - new Date(fromIso).getTime()) / 60_000));
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest === 0 ? `${hours} h` : `${hours} h ${rest} min`;
}

export function formatTimestamp(iso: string): string {
  return new Date(iso).toLocaleString("es-PE", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** RF-034: enlaces clicables en el texto del asesor/usuario. */
export function linkify(content: string): Array<{ text: string; href?: string }> {
  return content
    .split(/(https?:\/\/[^\s]+)/)
    .filter((part) => part.length > 0)
    .map((part) => (/^https?:\/\//.test(part) ? { text: part, href: part } : { text: part }));
}
