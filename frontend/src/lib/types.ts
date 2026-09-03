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

/** Espejo de `backend/agent/intents.py` (Intent StrEnum). */
export type Intent = "FAQ" | "CATALOG" | "ADVISOR" | "OTHER";

/**
 * Los únicos valores reales que `Conversation.handoff_reason` puede tener — los nombres de
 * regla de `backend/agent/heuristics.py` (`_ADVISOR_RULES`) más `advisor_intent` (el modelo,
 * no una regla, decidió ADVISOR) y `faq_no_evidence` (RAG sin evidencia). NUNCA texto libre:
 * el label en español vive en `format.ts` (`HANDOFF_REASON_LABEL`), igual que `STATUS_LABEL`.
 */
export type HandoffReason =
  | "advisor_request"
  | "bot_rejection"
  | "voice_channel"
  | "legal_threat"
  | "fraud_accusation"
  | "hostility"
  | "peruvian_complaint"
  | "funds_claim"
  | "advisor_intent"
  | "faq_no_evidence";

export interface Conversation {
  conversation_id: string;
  user_type: UserType;
  /** D-029: THREAD = hilo del bot; CASE = caso abierto por el formulario de asesor. */
  kind?: "THREAD" | "CASE";
  status: ConversationStatus;
  channel: string;
  bot_enabled: boolean;
  user_id: string | null;
  user_name: string | null;
  user_email: string | null;
  user_company: string | null;
  /** D-029: asunto del caso y contacto que dejo el anonimo en el formulario (RF-003). */
  title?: string | null;
  contact_name?: string | null;
  contact_email?: string | null;
  contact_phone?: string | null;
  source_conversation_id?: string | null;
  assigned_advisor_id: string | null;
  summary: string | null;
  message_count: number;
  unread_count: number;
  last_message_preview: string | null;
  last_message_at: string;
  handoff_requested_at: string | null;
  handoff_reason: HandoffReason | null;
  created_at: string;
  updated_at: string;
  closed_at: string | null;
  closed_by?: "ADVISOR" | "AUTO" | null;
}

export interface Message {
  conversation_id: string;
  message_id: string;
  /** SK real del mensaje (`ThreadOut.next_before/next_after` la usan para paginar/sondear). */
  message_key: string;
  sender_type: SenderType;
  sender_id: string | null;
  message_type: MessageType;
  status: MessageStatus;
  content: string | null;
  client_message_id: string | null;
  attachment: { url: string; content_type?: string } | null;
  /** D-029: valores estructurados del formulario + transcripción de origen (FORM_RESPONSE). */
  metadata: Record<string, unknown> | null;
  created_at: string;
}

/** Espejo de `backend/tickets/taxonomy.py` (StrEnum) — D-008 sigue ABIERTA, es propuesta. */
export type ProblemType =
  | "PAYMENT_ISSUE"
  | "REFUND_REQUEST"
  | "DEBT_DISPUTE"
  | "SANCTION_APPEAL"
  | "ENABLEMENT_ISSUE"
  | "RECEIPT_REQUEST"
  | "ACCOUNT_ACCESS"
  | "RISK_CATEGORY_DISPUTE"
  | "VISIT_ISSUE"
  | "PLATFORM_BUG"
  | "FORMAL_COMPLAINT"
  | "OTHER";

export type TicketCategory = "BILLING" | "COMPLIANCE" | "PURCHASE" | "ACCOUNT" | "LOGISTICS" | "TECHNICAL" | "GENERAL";

export type TicketPriority = "HIGH" | "MEDIUM" | "LOW";

export type TicketTag = "EN_VIVO" | "NEGOCIABLE" | "GANADOR" | "PLAZO_CORRIENDO" | "RECURRENTE";

export type TicketStatus = "PENDING" | "IN_PROGRESS" | "CLOSED";

/** Quién puso el `problem_type` actual — el dato con el que se mide si la propuesta de D-008 sirve. */
export type ClassificationSource = "RULES" | "ADVISOR";

/** Espejo de `TicketOut` (backend/api/routers/advisor.py) — 1:1 con la conversación escalada. */
export interface Ticket {
  ticket_id: string;
  conversation_id: string;
  status: TicketStatus;
  user_type: UserType;
  user_id: string | null;
  user_email: string | null;
  contact_name: string | null;
  contact_email: string | null;
  contact_phone: string | null;
  problem_type: ProblemType;
  category: TicketCategory;
  priority: TicketPriority;
  tags: TicketTag[];
  classification_source: ClassificationSource;
  classification_rule: string | null;
  title: string | null;
  description: string | null;
  collected_data: Record<string, unknown>;
  missing_data: string[];
  handoff_reason: string | null;
  assigned_advisor_id: string | null;
  assigned_at: string | null;
  resolution: string | null;
  /** A diferencia de `Conversation.closed_by` (ADVISOR/AUTO), aquí es el `advisor_id` real. */
  closed_by: string | null;
  created_at: string;
  updated_at: string;
  closed_at: string | null;
}

/** Un `problem_type` de `GET /advisor/taxonomy`, con la ayuda de contexto para el select. */
export interface TaxonomyProblemType {
  problem_type: ProblemType;
  category: TicketCategory;
  priority: TicketPriority;
  when: string;
  required: Array<{ name: string; label: string }>;
}

/** `GET /advisor/taxonomy` completo — `proposal: true` mientras D-008 siga abierta. */
export interface TaxonomyCatalog {
  proposal: boolean;
  decision: string;
  problem_types: TaxonomyProblemType[];
  categories: TicketCategory[];
  priorities: TicketPriority[];
  tags: TicketTag[];
}

/** Espejo de `AdvisorOut` (`GET /advisor/me`) — el asesor real detrás del JWT. */
export interface Advisor {
  advisor_id: string;
  name: string | null;
  email: string | null;
  role: string;
  status: "INVITED" | "ACTIVE" | "DISABLED";
  last_login_at: string | null;
}

/**
 * Espejo de `backend/agent/usage.py` en `develop` (tabla AIUsage) — NO existe todavía en la
 * rama actual (ver ANALISIS-METRICAS-DASHBOARD.md, Tarea A). No hay endpoint que agregue esto
 * entre conversaciones: es el vacío real que este mock simula para diseñar la vista de negocio.
 * `intent`/`source`/`handoff_reason` son ejes técnicos reales — NO la taxonomía de negocio de
 * D-008, que sigue sin existir.
 */
export interface RagFragmentRef {
  topic: string;
  score: number;
}

/**
 * Solo los campos que el set de métricas de negocio (Tarea B) realmente usa — el real en
 * `usage.py` trae más (tokens, latencia, modelo, provider): agregarlos aquí sin una métrica
 * que los necesite sería inflar el mock por las puras (Responsabilidad Y).
 */
export interface AIExecution {
  conversation_id: string;
  execution_id: string;
  intent: Intent | null;
  /** "rules" | "model" | "trivial_repeat_silent" | "guardrail:<kind>:<rule>" | "fallback" */
  source: string;
  estimated_cost_usd: number;
  rag_used: boolean;
  rag_fragments: RagFragmentRef[];
  created_at: string;
  /** "2026-08" — misma partición que el GSI `gsi_billing` real. */
  billing_month: string;
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
