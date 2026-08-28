"use client";

import { useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import Button from "@/concorde/components/Button";
import AvatarZone from "@/concorde/components/AvatarZone";
import StatusBadge from "@/components/StatusBadge";
import MessageBubble from "@/components/MessageBubble";
import { ArrowLeftIcon, PaperclipIcon } from "@/components/icons";
import { CURRENT_ADVISOR, MOCK_CONVERSATIONS, MOCK_MESSAGES } from "@/lib/mock-data";
import { formatWaitTime, MOCK_NOW_MS, SENDER_LABEL } from "@/lib/format";
import type { Conversation, Message } from "@/lib/types";

function senderLabelFor(message: Message, conversation: Conversation): string {
  if (message.sender_type === "USER") return conversation.user_name ?? "Usuario";
  if (message.sender_type === "ADVISOR") return CURRENT_ADVISOR.display_name;
  return SENDER_LABEL[message.sender_type];
}

/**
 * Vista de conversación del cockpit (RF-033/034/035/036/037/038). Vive dentro
 * de inbox/layout.tsx: el rail de la cola ya está a la izquierda en desktop, así
 * que aquí solo el hilo + contexto — el volver a "Bandeja" (ArrowLeftIcon) solo
 * hace falta en mobile, donde el rail se esconde (RF-047).
 */
export default function ConversationDetailPage() {
  const { id } = useParams<{ id: string }>();
  const conversation = MOCK_CONVERSATIONS.find((c) => c.conversation_id === id);
  const messages = MOCK_MESSAGES[id] ?? [];

  const [draft, setDraft] = useState("");
  const [retryFailed, setRetryFailed] = useState(true);
  // RF-029: la toma es una acción explícita y atómica del asesor, no un efecto de abrir el
  // hilo. Este flag es solo de demo (no hay backend); en real vendría de assigned_advisor_id.
  const [takenByMe, setTakenByMe] = useState(false);

  if (!conversation) {
    return (
      <div className="flex flex-1 items-center justify-center rounded-2xl bg-white p-10 text-center text-sm text-neutral-500 shadow-sm">
        No se encontró la conversación {id}.{" "}
        <Link href="/advisor/inbox" className="ml-1 underline">
          Volver a la cola
        </Link>
      </div>
    );
  }

  const isPendingUnassigned =
    conversation.status === "PENDING_ADVISOR" && !conversation.assigned_advisor_id && !takenByMe;
  const assignedToOther =
    conversation.assigned_advisor_id !== null &&
    conversation.assigned_advisor_id !== CURRENT_ADVISOR.advisor_id;
  const canReply =
    !assignedToOther &&
    (conversation.status === "IN_ATTENTION" || (conversation.status === "PENDING_ADVISOR" && takenByMe));

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 lg:flex-row">
      <section className="flex min-h-0 min-w-0 flex-1 flex-col rounded-2xl bg-white shadow-sm">
        <header className="flex items-center justify-between gap-3 border-b border-black/5 px-5 py-4">
          <div className="flex min-w-0 items-center gap-3">
            <Link
              href="/advisor/inbox"
              className="flex items-center rounded-lg text-neutral-500 transition hover:text-neutral-600 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--vmc-color-vault-500)] lg:hidden"
              aria-label="Volver a la cola"
            >
              <ArrowLeftIcon width={18} height={18} />
            </Link>
            <AvatarZone size="sm" title={conversation.user_name ?? "Anónimo"} />
            {/* ponytail: el badge de estado (nowrap) le ganaba el espacio al nombre en mobile
                y lo truncaba a 2-3 letras ("Jorge S…") — bajarlo a su propia línea le devuelve
                el ancho al nombre, que es el dato que el asesor realmente necesita ver. */}
            <div className="min-w-0 flex-1">
              <p className="truncate text-base font-semibold text-[#191C1C]">
                {conversation.user_name ?? "Usuario anónimo"}
              </p>
              <span className="mt-0.5 inline-flex sm:hidden">
                <StatusBadge status={conversation.status} />
              </span>
            </div>
            <span className="hidden flex-shrink-0 sm:inline-flex">
              <StatusBadge status={conversation.status} />
            </span>
          </div>
          {canReply && (
            <button
              type="button"
              className="flex-shrink-0 rounded-full border border-neutral-200 px-3 py-1.5 text-xs font-semibold text-neutral-500 transition hover:border-neutral-300 hover:text-neutral-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--vmc-color-vault-500)]"
            >
              Cerrar caso
            </button>
          )}
        </header>

        <div className="flex min-h-0 flex-1 flex-col justify-end gap-3 overflow-y-auto px-5 py-4">
          {messages.map((message, i) => {
            const prev = messages[i - 1];
            const showLabel =
              message.message_type !== "SYSTEM" &&
              (!prev ||
                prev.message_type === "SYSTEM" ||
                prev.sender_type !== message.sender_type ||
                prev.sender_id !== message.sender_id);
            return (
              <MessageBubble
                key={message.message_id}
                message={message}
                senderLabel={showLabel ? senderLabelFor(message, conversation) : undefined}
              />
            );
          })}

          {retryFailed && canReply && (
            <div className="flex justify-end">
              <div className="alert-card max-w-md rounded-2xl px-4 py-3 text-sm">
                No se pudo enviar: &quot;Un momento, reviso tu caso&quot;
                <button
                  type="button"
                  onClick={() => setRetryFailed(false)}
                  className="mt-1 block text-xs font-semibold underline decoration-2 underline-offset-2 transition-opacity hover:opacity-80"
                >
                  Reintentar (RF-037/038 · mismo client_message_id, no duplica)
                </button>
              </div>
            </div>
          )}
        </div>

        <footer className="border-t border-black/5 px-5 py-4">
          {isPendingUnassigned ? (
            <div className="flex flex-col gap-3 rounded-2xl bg-[color:var(--vmc-color-orange-600)]/10 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
              <p className="text-sm text-[#9A4A0F]">
                Nadie ha tomado este caso todavía. Tómalo para poder responder (RF-029).
              </p>
              <Button variant="secondary-sm" onClick={() => setTakenByMe(true)}>
                Tomar conversación
              </Button>
            </div>
          ) : assignedToOther ? (
            <p className="text-center text-sm text-neutral-500">
              {conversation.assigned_advisor_id} ya tomó este caso — solo lectura.
            </p>
          ) : canReply ? (
            <div className="flex items-end gap-3">
              <button
                type="button"
                title="Adjuntar imagen (selector / pegado / drag & drop — RF-041)"
                className="flex h-11 w-11 flex-shrink-0 items-center justify-center rounded-full border border-neutral-200 text-neutral-500 transition hover:border-neutral-300 hover:text-neutral-700"
              >
                <PaperclipIcon />
              </button>
              <textarea
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                placeholder="Escribe una respuesta…"
                rows={1}
                className="min-h-11 flex-1 resize-none rounded-2xl border border-neutral-200 px-4 py-2.5 text-sm outline-none focus:border-[color:var(--vmc-color-vault-500)]"
              />
              <Button variant="secondary-sm" onClick={() => setDraft("")}>
                Enviar
              </Button>
            </div>
          ) : (
            <p className="text-center text-sm text-neutral-500">
              Sin handoff activo — el bot está atendiendo (RF-025). Nada que responder desde acá.
            </p>
          )}
        </footer>
      </section>

      <aside className="flex w-full flex-shrink-0 flex-col gap-4 rounded-2xl bg-white p-5 shadow-sm lg:w-80">
        <div>
          <h2 className="text-xs font-bold uppercase tracking-wide text-neutral-500">Usuario</h2>
          <dl className="mt-2.5 space-y-1.5 text-sm">
            <Field label="Nombre" value={conversation.user_name} />
            <Field label="Correo" value={conversation.user_email} />
            <Field label="Empresa" value={conversation.user_company} />
            <Field label="ID VMC" value={conversation.user_id} />
          </dl>
          <p className="mt-2.5 text-xs text-neutral-400">
            Campos soportados hoy por el modelo de datos. Set definitivo pendiente de D-010.
          </p>
        </div>

        {/* Lo que la IA ya resolvió — tinte violeta (identidad de Subastín, el asistente),
            para que se distinga a simple vista de los datos crudos del usuario de arriba. */}
        <div className="rounded-2xl bg-[color:var(--vmc-color-vault-500)]/5 p-3.5">
          <h2 className="flex items-center gap-1.5 text-xs font-bold uppercase tracking-wide text-[color:var(--vmc-color-vault-700)]">
            <span className="flex h-4 items-center rounded-full bg-[color:var(--vmc-color-vault-500)] px-1.5 text-[10px] font-bold text-white">
              IA
            </span>
            Resumen
          </h2>
          <p className="mt-2 text-sm text-neutral-700">{conversation.summary ?? "Sin resumen todavía."}</p>
        </div>

        {conversation.handoff_reason && (
          <div className="rounded-2xl bg-[color:var(--vmc-color-orange-600)]/5 p-3.5">
            <h2 className="text-xs font-bold uppercase tracking-wide text-[#9A4A0F]">Derivación</h2>
            <p className="mt-2 text-sm text-neutral-700">{conversation.handoff_reason}</p>
            {conversation.handoff_requested_at && (
              <p className="mt-1.5 text-xs text-[#9A4A0F]/70">
                Esperando hace {formatWaitTime(conversation.handoff_requested_at, MOCK_NOW_MS)}
              </p>
            )}
          </div>
        )}
      </aside>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string | null }) {
  return (
    <div className="flex justify-between gap-3">
      <dt className="text-neutral-500">{label}</dt>
      <dd className="text-right font-medium text-[#191C1C]">{value ?? "—"}</dd>
    </div>
  );
}
