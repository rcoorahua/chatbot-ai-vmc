import type { ConversationStatus } from "./types";

/**
 * UNA paleta por estado para el pill (StatusBadge), el punto de la cola (QueueRow) y las
 * barras del dashboard. Antes cada componente traia la suya y CLOSED ya tenia dos grises
 * distintos (#C7C9CC en la cola, #99A1AF en el dashboard; auditoria 2026-09-06).
 */
export const STATUS_COLOR: Record<ConversationStatus, string> = {
  BOT_ATTENDING: "#8460E5",
  PENDING_ADVISOR: "#ED8936",
  IN_ATTENTION: "#00AEB1",
  CLOSED: "#99A1AF",
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
  BOT_ATTENDING: "#3B1782",
  PENDING_ADVISOR: "#9A4A0F",
  IN_ATTENTION: "#00696B",
  CLOSED: "#5C6266",
};
