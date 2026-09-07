import type { ConversationStatus, ProblemType, SenderType } from "./types";

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

/**
 * T7: motivo de derivación en español. Hoy el único valor que produce el backend es `user_form`
 * (el caso nace del formulario de asesor, D-029); un código nuevo se muestra tal cual en vez
 * de fallar. El mapa de 10 códigos de versiones previas describía reglas que ya no derivan.
 */
export function handoffReasonLabel(reason: string): string {
  return reason === "user_form" ? "Pidió hablar con un asesor (formulario)" : reason;
}

/**
 * `problem_type` legible mientras D-008 siga abierta: el catálogo (`GET /advisor/taxonomy`) no
 * trae label en español todavía, y copiar la lista aquí es justo lo que CLAUDE.md prohíbe.
 * "PAYMENT_ISSUE" → "Payment issue".
 */
export function problemTypeLabel(problemType: ProblemType | string): string {
  const words = problemType.toLowerCase().replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

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
