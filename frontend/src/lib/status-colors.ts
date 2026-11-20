import type { ConversationStatus } from "./types";

/**
 * UNA paleta por estado para el pill de estado (dashboard), el punto de la cola (QueueRow) y las
 * barras del dashboard. Antes cada componente traia la suya y CLOSED ya tenia dos grises
 * distintos (#C7C9CC en la cola, #99A1AF en el dashboard; auditoria 2026-09-06).
 */
export const STATUS_COLOR: Record<ConversationStatus, string> = {
  BOT_ATTENDING: "var(--vmc-color-vault-500)",
  PENDING_ADVISOR: "var(--vmc-color-orange-600)",
  IN_ATTENTION: "var(--vmc-color-teal-500)",
  CLOSED: "var(--vmc-color-neutral-700)",
};

/** Fondo suave del pill. */
export const STATUS_BG: Record<ConversationStatus, string> = {
  BOT_ATTENDING: "#F1EDFD",
  PENDING_ADVISOR: "#FDF0E4",
  IN_ATTENTION: "#E3F8F8",
  CLOSED: "#EEEEEE",
};

/** Tono oscuro (texto del pill, cifras del dashboard): el unico seguro en contraste sobre blanco. */
export const STATUS_DEEP_COLOR: Record<ConversationStatus, string> = {
  BOT_ATTENDING: "var(--vmc-color-vault-700)",
  PENDING_ADVISOR: "#9A4A0F",
  IN_ATTENTION: "#00696B",
  CLOSED: "#5C6266",
};
