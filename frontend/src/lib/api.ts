import type {
  Advisor,
  Conversation,
  ConversationStatus,
  Message,
  ProblemType,
  TaxonomyCatalog,
  Ticket,
  TicketCategory,
  TicketPriority,
  TicketStatus,
  TicketTag,
} from "./types";

/**
 * Cliente HTTP de `/advisor/*` (contrato real en backend/api/routers/advisor.py — leído campo
 * a campo, no generado: no hay OpenAPI-codegen en este repo todavía, ver DETAILS.md §4.21/paso
 * 16). Un archivo, sin librería (fetch nativo) — nada que instalar para lo que esto necesita.
 *
 * ponytail: el token de asesor se guarda en localStorage bajo ADVISOR_TOKEN_KEY. No hay login
 * real (Cognito Hosted UI) conectado todavía — en dev se pega el token de
 * `python -m scripts.advisor_token` a mano con `setAdvisorToken(...)` desde la consola.
 * Reemplazar cuando `advisor/login` deje de ser un mock.
 */

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const ADVISOR_TOKEN_KEY = "subastin_advisor_token";

export function getAdvisorToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(ADVISOR_TOKEN_KEY);
}

export function setAdvisorToken(token: string): void {
  window.localStorage.setItem(ADVISOR_TOKEN_KEY, token);
}

export function clearAdvisorToken(): void {
  window.localStorage.removeItem(ADVISOR_TOKEN_KEY);
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: unknown,
  ) {
    super(typeof detail === "string" ? detail : `API respondió ${status}`);
  }
}

/** Mensaje legible para mostrar tal cual en la UI (no un log técnico). */
export function apiErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 401) {
      return "Sesión de asesor inválida o vencida. (dev: pega un token nuevo con setAdvisorToken() en la consola).";
    }
    if (typeof err.detail === "string") return err.detail;
    if (err.detail && typeof err.detail === "object" && "detail" in err.detail) {
      const nested = (err.detail as { detail: unknown }).detail;
      if (typeof nested === "string") return nested;
    }
    return err.message;
  }
  return "No se pudo conectar con el servidor.";
}

/** `undefined`/`false` se omiten — así los callers pasan el objeto de filtros tal cual. */
function query(params: object): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== false) search.set(key, String(value));
  }
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getAdvisorToken();
  const res = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init?.headers,
    },
  });
  const body = res.status === 204 ? null : await res.json().catch(() => null);
  // FastAPI envuelve HTTPException(status, detail) como {"detail": detail} — detail puede ser
  // un string (404 normal) o un objeto (409 de take(), que además trae `conversation`).
  if (!res.ok) throw new ApiError(res.status, body && typeof body === "object" && "detail" in body ? body.detail : body);
  return body as T;
}

// ───────────────────────────────────── /advisor/me ─────────────────────────────────────

export function getMe(): Promise<Advisor> {
  return apiFetch<Advisor>("/advisor/me");
}

// ───────────────────────────────── /advisor/conversations ─────────────────────────────────

export interface ConversationFilters {
  status?: ConversationStatus;
  mine?: boolean;
  limit?: number;
}

export async function getConversations(filters: ConversationFilters = {}): Promise<Conversation[]> {
  const { conversations } = await apiFetch<{ conversations: Conversation[] }>(
    `/advisor/conversations${query(filters)}`,
  );
  return conversations;
}

export function getConversation(conversationId: string): Promise<Conversation> {
  return apiFetch<Conversation>(`/advisor/conversations/${conversationId}`);
}

export interface ThreadPage {
  conversation: Conversation;
  messages: Message[];
  next_before: string | null;
  has_more: boolean;
  next_after: string | null;
}

export interface MessagesFilters {
  before?: string;
  after?: string;
  limit?: number;
}

export function getMessages(conversationId: string, filters: MessagesFilters = {}): Promise<ThreadPage> {
  return apiFetch<ThreadPage>(`/advisor/conversations/${conversationId}/messages${query(filters)}`);
}

/** 409 si otro asesor ya la tomó — `ApiError.detail` trae `{ detail, conversation }` (AC-005). */
export function takeConversation(conversationId: string): Promise<Conversation> {
  return apiFetch<Conversation>(`/advisor/conversations/${conversationId}/take`, { method: "POST" });
}

export interface PostMessageResult {
  message: Message;
  duplicate: boolean;
}

/** `clientMessageId`: 8-64 chars `[A-Za-z0-9_-]` — mismo contrato idempotente que el widget. */
export function postAdvisorMessage(
  conversationId: string,
  clientMessageId: string,
  content: string,
): Promise<PostMessageResult> {
  return apiFetch<PostMessageResult>(`/advisor/conversations/${conversationId}/messages`, {
    method: "POST",
    body: JSON.stringify({ client_message_id: clientMessageId, content }),
  });
}

export function closeConversation(conversationId: string, resolution?: string): Promise<Conversation> {
  return apiFetch<Conversation>(`/advisor/conversations/${conversationId}/close`, {
    method: "POST",
    body: JSON.stringify({ resolution: resolution ?? null }),
  });
}

// ──────────────────────────────── /advisor/taxonomy, /advisor/tickets ────────────────────────────────

export function getTaxonomy(): Promise<TaxonomyCatalog> {
  return apiFetch<TaxonomyCatalog>("/advisor/taxonomy");
}

export interface TicketFilters {
  status?: TicketStatus;
  mine?: boolean;
  limit?: number;
}

export async function getTickets(filters: TicketFilters = {}): Promise<Ticket[]> {
  const { tickets } = await apiFetch<{ tickets: Ticket[] }>(`/advisor/tickets${query(filters)}`);
  return tickets;
}

/** Crea el ticket si el caso llegó sin uno (ver docstring del endpoint) — 404 si el bot la atiende. */
export function getTicketForConversation(conversationId: string): Promise<Ticket> {
  return apiFetch<Ticket>(`/advisor/conversations/${conversationId}/ticket`);
}

export interface TicketPatch {
  problem_type?: ProblemType;
  category?: TicketCategory;
  priority?: TicketPriority;
  tags?: TicketTag[];
  collected_data?: Record<string, unknown>;
}

/** Confirmar/corregir la clasificación (RF-024). 409 si el ticket ya está cerrado. */
export function patchTicket(ticketId: string, patch: TicketPatch): Promise<Ticket> {
  return apiFetch<Ticket>(`/advisor/tickets/${ticketId}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}
