/**
 * Contrato de datos espejo de backend/conversations/models.py (RF-008/009, T7).
 * Los valores de los enums son EXACTOS a los del backend: cambia solo si cambia el modelo ahí.
 */

export type ConversationStatus =
  | "BOT_ATTENDING"
  | "PENDING_ADVISOR"
  | "IN_ATTENTION"
  | "CLOSED";

export type UserType = "AUTHENTICATED" | "ANONYMOUS";

export type SenderType = "USER" | "BOT" | "ADVISOR" | "SYSTEM";

export type MessageType = "TEXT" | "IMAGE" | "SYSTEM";

export type MessageStatus = "RECEIVED" | "QUEUE_FAILED" | "PROCESSED" | "FAILED" | "DELIVERED";

export interface Conversation {
  conversation_id: string;
  user_type: UserType;
  status: ConversationStatus;
  channel: string;
  bot_enabled: boolean;
  user_id: string | null;
  user_name: string | null;
  user_email: string | null;
  user_company: string | null;
  assigned_advisor_id: string | null;
  summary: string | null;
  message_count: number;
  unread_count: number;
  last_message_preview: string | null;
  last_message_at: string;
  handoff_requested_at: string | null;
  handoff_reason: string | null;
  created_at: string;
  updated_at: string;
  closed_at: string | null;
}

export interface Message {
  conversation_id: string;
  message_id: string;
  sender_type: SenderType;
  sender_id: string | null;
  message_type: MessageType;
  status: MessageStatus;
  content: string | null;
  attachment: { url: string; content_type?: string } | null;
  created_at: string;
}

/**
 * Advisor real (backend/advisors/models.py) es un stub — status INVITED/ACTIVE/DISABLED,
 * role ADVISOR (RF-007). No hay campo `name` definido todavía: se usa uno de sesión aquí
 * solo para el saludo del header, no como contrato.
 */
export interface AdvisorSession {
  advisor_id: string;
  display_name: string;
}
