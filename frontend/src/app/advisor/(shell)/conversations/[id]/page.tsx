"use client";

import { useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import Button from "@/concorde/components/Button";
import Input from "@/concorde/components/Input";
import AvatarZone from "@/concorde/components/AvatarZone";
import StatusBadge from "@/components/StatusBadge";
import MessageBubble from "@/components/MessageBubble";
import { CURRENT_ADVISOR, MOCK_CONVERSATIONS, MOCK_MESSAGES } from "@/lib/mock-data";
import { formatWaitTime, MOCK_NOW_MS } from "@/lib/format";

/**
 * Vista de conversación del asesor (RF-033/034/035/036/037/038). El panel contextual solo
 * muestra los campos que YA existen en Conversation (nombre/correo/empresa/id/resumen) — el
 * set definitivo de campos de usuario sigue bloqueado por D-010, así que no se inventan más.
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
      <div className="text-sm text-neutral-500">
        No se encontró la conversación {id}.{" "}
        <Link href="/advisor/inbox" className="underline">
          Volver a la bandeja
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
    <div className="flex h-full gap-6">
      <section className="flex flex-1 flex-col rounded-2xl bg-white shadow-sm">
        <header className="flex items-center justify-between border-b border-black/5 px-5 py-4">
          <div className="flex items-center gap-3">
            <Link href="/advisor/inbox" className="text-sm text-neutral-400 hover:text-neutral-600">
              ← Bandeja
            </Link>
            <AvatarZone size="sm" title={conversation.user_name ?? "Anónimo"} />
            <p className="font-semibold text-[#191C1C]">{conversation.user_name ?? "Usuario anónimo"}</p>
            <StatusBadge status={conversation.status} />
          </div>
          {canReply && <Button variant="outline">Cerrar caso</Button>}
        </header>

        <div className="flex-1 space-y-3 overflow-y-auto px-5 py-4">
          {messages.map((message) => (
            <MessageBubble key={message.message_id} message={message} />
          ))}

          {retryFailed && canReply && (
            <div className="flex flex-col items-end gap-1">
              <div className="max-w-md rounded-2xl border border-dashed border-red-300 bg-red-50 px-4 py-2.5 text-sm text-red-600">
                No se pudo enviar: &quot;Un momento, reviso tu caso&quot;
              </div>
              <button
                type="button"
                onClick={() => setRetryFailed(false)}
                className="px-1 text-xs font-semibold text-red-500 underline"
              >
                Reintentar (RF-037/038 · mismo client_message_id, no duplica)
              </button>
            </div>
          )}
        </div>

        <footer className="border-t border-black/5 px-5 py-4">
          {isPendingUnassigned ? (
            <div className="flex items-center justify-between rounded-2xl bg-[color:var(--vmc-color-orange-600)]/10 px-4 py-3">
              <p className="text-sm text-[#9A4A0F]">
                Nadie ha tomado este caso todavía. Tómalo para poder responder (RF-029).
              </p>
              <Button variant="secondary-sm" onClick={() => setTakenByMe(true)}>
                Tomar conversación
              </Button>
            </div>
          ) : assignedToOther ? (
            <p className="text-center text-sm text-neutral-400">
              {conversation.assigned_advisor_id} ya tomó este caso — solo lectura.
            </p>
          ) : canReply ? (
            <div className="flex items-end gap-3">
              <button
                type="button"
                title="Adjuntar imagen (selector / pegado / drag & drop — RF-041)"
                className="flex h-11 w-11 flex-shrink-0 items-center justify-center rounded-full border border-neutral-200 text-lg"
              >
                📎
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
            <p className="text-center text-sm text-neutral-400">
              Sin handoff activo — el bot está atendiendo (RF-025). Nada que responder desde acá.
            </p>
          )}
        </footer>
      </section>

      <aside className="flex w-80 flex-shrink-0 flex-col gap-4 rounded-2xl bg-white p-5 shadow-sm">
        <div>
          <h2 className="text-sm font-bold uppercase tracking-wide text-neutral-400">Usuario</h2>
          <dl className="mt-2 space-y-1.5 text-sm">
            <Field label="Nombre" value={conversation.user_name} />
            <Field label="Correo" value={conversation.user_email} />
            <Field label="Empresa" value={conversation.user_company} />
            <Field label="ID VMC" value={conversation.user_id} />
          </dl>
          <p className="mt-2 text-xs text-neutral-400">
            Campos soportados hoy por el modelo de datos. Set definitivo pendiente de D-010.
          </p>
        </div>

        <div>
          <h2 className="text-sm font-bold uppercase tracking-wide text-neutral-400">Resumen (IA)</h2>
          <p className="mt-1 text-sm text-neutral-600">{conversation.summary ?? "Sin resumen todavía."}</p>
        </div>

        {conversation.handoff_reason && (
          <div>
            <h2 className="text-sm font-bold uppercase tracking-wide text-neutral-400">Derivación</h2>
            <p className="mt-1 text-sm text-neutral-600">{conversation.handoff_reason}</p>
            {conversation.handoff_requested_at && (
              <p className="mt-0.5 text-xs text-neutral-400">
                Esperando hace {formatWaitTime(conversation.handoff_requested_at, MOCK_NOW_MS)}
              </p>
            )}
          </div>
        )}

        <div>
          <h2 className="text-sm font-bold uppercase tracking-wide text-neutral-400">Buscar en VMC</h2>
          <div className="mt-2">
            <Input placeholder="Buscar por ID VMC…" className="w-full" disabled />
          </div>
          <p className="mt-1 text-xs text-neutral-400">Solo lectura (RF-051) — sin integración aún.</p>
        </div>
      </aside>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string | null }) {
  return (
    <div className="flex justify-between gap-3">
      <dt className="text-neutral-400">{label}</dt>
      <dd className="text-right font-medium text-[#191C1C]">{value ?? "—"}</dd>
    </div>
  );
}
