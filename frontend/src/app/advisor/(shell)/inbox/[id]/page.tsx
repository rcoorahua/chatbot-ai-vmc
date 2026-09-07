"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import Button from "@/concorde/components/Button";
import AvatarZone from "@/concorde/components/AvatarZone";
import StatusBadge from "@/components/StatusBadge";
import MessageBubble from "@/components/MessageBubble";
import { ArrowLeftIcon, ChevronRightIcon, PaperclipIcon } from "@/components/icons";
import { ApiError, apiErrorMessage, closeConversation, getMessages, postAdvisorMessage, takeConversation } from "@/lib/api";
import { useAdvisor } from "@/lib/advisor-context";
import { SENDER_LABEL, formatWaitTime, handoffReasonLabel } from "@/lib/format";
import type { Conversation, Message } from "@/lib/types";

/**
 * Vista de conversación del cockpit (RF-033/034/035/036/037/038). Vive dentro
 * de inbox/layout.tsx: el rail de la cola ya está a la izquierda en desktop, así
 * que aquí solo el hilo + contexto — el volver a "Bandeja" (ArrowLeftIcon) solo
 * hace falta en mobile, donde el rail se esconde (RF-047).
 *
 * ponytail: solo el último `getMessages` (20 mensajes, sin paginar) — `has_more`/`next_before`
 * ya vienen del backend; agregar "ver anteriores" cuando haga falta, no antes.
 */
export default function ConversationDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { advisor } = useAdvisor();
  const [now] = useState(() => Date.now());

  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  // Igual que inbox/layout.tsx: loading se DERIVA comparando el id resuelto/fallido contra el
  // id vigente — nunca un setState síncrono en el cuerpo del efecto (react-hooks/set-state-in-effect).
  const [loadedId, setLoadedId] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<{ id: string; message: string } | null>(null);

  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [sendFailure, setSendFailure] = useState<{ clientMessageId: string; content: string; message: string } | null>(
    null,
  );
  const [taking, setTaking] = useState(false);
  const [closing, setClosing] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const loading = loadedId !== id && loadError?.id !== id;

  useEffect(() => {
    let cancelled = false;
    getMessages(id)
      .then((page) => {
        if (cancelled) return;
        setConversation(page.conversation);
        setMessages(page.messages);
        setLoadedId(id);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setLoadError({ id, message: apiErrorMessage(err) });
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  function senderLabelFor(message: Message): string {
    if (message.sender_type === "USER") return conversation?.user_name ?? "Usuario";
    if (message.sender_type === "ADVISOR") return advisor?.name ?? advisor?.email ?? "Asesor";
    return SENDER_LABEL[message.sender_type];
  }

  async function handleTake(): Promise<void> {
    setTaking(true);
    setActionError(null);
    try {
      setConversation(await takeConversation(id));
    } catch (err) {
      // AC-005: si otro asesor ya la tomó, el 409 trae su estado actual — se refleja igual,
      // no solo el mensaje de error, para que la pantalla no quede desincronizada.
      if (err instanceof ApiError && err.status === 409 && err.detail && typeof err.detail === "object" && "conversation" in err.detail) {
        setConversation((err.detail as { conversation: Conversation }).conversation);
      }
      setActionError(apiErrorMessage(err));
    } finally {
      setTaking(false);
    }
  }

  async function handleClose(): Promise<void> {
    setClosing(true);
    setActionError(null);
    try {
      setConversation(await closeConversation(id));
    } catch (err) {
      setActionError(apiErrorMessage(err));
    } finally {
      setClosing(false);
    }
  }

  async function sendMessage(clientMessageId: string, content: string): Promise<void> {
    setSending(true);
    setSendFailure(null);
    try {
      const { message } = await postAdvisorMessage(id, clientMessageId, content);
      setMessages((prev) => [...prev, message]);
      setDraft("");
    } catch (err) {
      // Mismo client_message_id: reintentar no duplica (RF-037/038), sea cual sea el error.
      setSendFailure({ clientMessageId, content, message: apiErrorMessage(err) });
    } finally {
      setSending(false);
    }
  }

  function handleSend(): void {
    const content = draft.trim();
    if (!content || sending) return;
    void sendMessage(crypto.randomUUID(), content);
  }

  if (loading) {
    return (
      <div className="flex flex-1 items-center justify-center rounded-2xl bg-white shadow-sm">
        <div className="h-8 w-8 animate-pulse rounded-full bg-neutral-200" />
      </div>
    );
  }

  if (!conversation || conversation.conversation_id !== id) {
    const message = loadError?.id === id ? loadError.message : `No se encontró la conversación ${id}.`;
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-2 rounded-2xl bg-white p-10 text-center text-sm shadow-sm">
        <p className={loadError?.id === id ? "text-[#9A4A0F]" : "text-neutral-500"}>{message}</p>
        <Link href="/advisor/inbox" className="underline">
          Volver a la cola
        </Link>
      </div>
    );
  }

  const isPendingUnassigned = conversation.status === "PENDING_ADVISOR" && !conversation.assigned_advisor_id;
  const assignedToOther =
    conversation.assigned_advisor_id !== null && conversation.assigned_advisor_id !== advisor?.advisor_id;
  const canReply = !assignedToOther && conversation.status === "IN_ATTENTION";

  return (
    // Mobile y desktop comparten el mismo esqueleto: la <section> del hilo llena su alto
    // (acotado por <main>) y el ÚNICO scroll es el de los mensajes. Así la cabecera y la
    // barra de acción quedan fijas —el botón "Tomar" pegado al borde inferior— sin
    // `position:fixed`. En mobile la tarjeta sangra hasta los bordes de <main> (bleed con
    // margen negativo) para que la barra de acción quede a ras de la pantalla. El panel de
    // contexto es un <aside> en desktop; en mobile va como bloque plegable al inicio del hilo.
    <div className="flex min-h-0 flex-1 flex-col gap-4 max-lg:-mx-4 max-lg:-mb-4 sm:max-lg:-mx-6 sm:max-lg:-mb-6 lg:flex-row">
      <section className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden rounded-2xl bg-white shadow-sm max-lg:rounded-b-none max-lg:shadow-none">
        <header className="flex flex-shrink-0 items-center justify-between gap-3 border-b border-black/5 px-4 py-3.5 sm:px-5">
          <div className="flex min-w-0 items-center gap-3">
            <Link
              href="/advisor/inbox"
              className="-ml-1 flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-full text-neutral-500 transition hover:bg-neutral-100 hover:text-neutral-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--vmc-color-vault-500)] lg:hidden"
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
              onClick={() => void handleClose()}
              disabled={closing}
              className="flex-shrink-0 rounded-full border border-neutral-200 px-3 py-1.5 text-xs font-semibold text-neutral-500 transition hover:border-neutral-300 hover:text-neutral-700 disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--vmc-color-vault-500)]"
            >
              {closing ? "Cerrando…" : "Cerrar caso"}
            </button>
          )}
        </header>

        <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto px-4 py-4 sm:px-5">
          {/* Contexto — en mobile el <aside> no se renderiza; su info va acá, plegable. */}
          <MobileContext conversation={conversation} now={now} />

          {actionError && <p className="text-center text-xs text-[#9A4A0F]">{actionError}</p>}

          {/* Los mensajes se pegan abajo (convención de chat): crecen hacia arriba. */}
          <div className="flex flex-1 flex-col justify-end gap-3">
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
                  senderLabel={showLabel ? senderLabelFor(message) : undefined}
                />
              );
            })}

            {sendFailure && canReply && (
              <div className="flex justify-end">
                <div className="alert-card max-w-md rounded-2xl px-4 py-3 text-sm">
                  No se pudo enviar: &quot;{sendFailure.content}&quot; — {sendFailure.message}
                  <button
                    type="button"
                    onClick={() => void sendMessage(sendFailure.clientMessageId, sendFailure.content)}
                    disabled={sending}
                    className="mt-1 block text-xs font-semibold underline decoration-2 underline-offset-2 transition-opacity hover:opacity-80 disabled:opacity-50"
                  >
                    Reintentar (RF-037/038 · mismo client_message_id, no duplica)
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>

        <footer className="flex-shrink-0 border-t border-black/5 bg-white px-4 py-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] sm:px-5 lg:pb-3">
          {isPendingUnassigned ? (
            <div className="flex flex-col gap-2.5 sm:flex-row sm:items-center sm:justify-between sm:gap-3">
              <p className="text-xs text-neutral-500 sm:flex-1 sm:text-sm">
                Nadie ha tomado este caso todavía. Tómalo para poder responder.
              </p>
              <Button
                variant="secondary-sm"
                className="w-full sm:w-auto"
                onClick={() => void handleTake()}
                disabled={taking}
              >
                {taking ? "Tomando…" : "Tomar conversación"}
              </Button>
            </div>
          ) : assignedToOther ? (
            <p className="py-1 text-center text-sm text-neutral-500">
              Otro asesor ya tomó este caso — solo lectura.
            </p>
          ) : canReply ? (
            <div className="flex items-end gap-2 sm:gap-3">
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
                className="min-h-11 min-w-0 flex-1 resize-none rounded-2xl border border-neutral-200 px-4 py-2.5 text-sm outline-none focus:border-[color:var(--vmc-color-vault-500)]"
              />
              <Button
                variant="secondary-sm"
                className="!min-w-0 flex-shrink-0"
                onClick={handleSend}
                disabled={sending || !draft.trim()}
              >
                {sending ? "Enviando…" : "Enviar"}
              </Button>
            </div>
          ) : (
            <p className="py-1 text-center text-sm text-neutral-500">
              El bot está atendiendo (RF-025). Nada que responder desde acá.
            </p>
          )}
        </footer>
      </section>

      <aside className="hidden w-full flex-shrink-0 flex-col gap-4 rounded-2xl bg-white p-5 shadow-sm lg:flex lg:w-80">
        <div>
          <h2 className="text-xs font-bold uppercase tracking-wide text-neutral-500">Usuario</h2>
          <dl className="mt-2.5 space-y-1.5 text-sm">
            {/* D-010 (cerrada 2026-09-07): el CUU va primero porque es el codigo que el
                usuario ve en VMC y el que dice por telefono. */}
            <Field label="CUU" value={conversation.user_cuu} />
            <Field label="Correo" value={conversation.user_email} />
            <Field label="ID VMC" value={conversation.user_id} />
            <Field label="Nombre" value={conversation.user_name} />
            <Field label="Empresa" value={conversation.user_company} />
          </dl>
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
            <p className="mt-2 text-sm text-neutral-700">{handoffReasonLabel(conversation.handoff_reason)}</p>
            {conversation.handoff_requested_at && (
              <p className="mt-1.5 text-xs text-[#9A4A0F]/70">
                Esperando hace {formatWaitTime(conversation.handoff_requested_at, now)}
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
      <dd className="min-w-0 truncate text-right font-medium text-[#191C1C]">{value ?? "—"}</dd>
    </div>
  );
}

/**
 * Contexto del caso para mobile: el <aside> de la derecha no se renderiza bajo `lg`, así que
 * su info va acá, arriba del hilo. La derivación (por qué llegó, cuánto lleva esperando) va
 * siempre visible; el resto —datos del usuario, resumen de la IA— en un <details> nativo,
 * plegado salvo que aún nadie haya tomado el caso (ahí el asesor necesita todo para decidir).
 */
function MobileContext({ conversation, now }: { conversation: Conversation; now: number }) {
  const untaken = conversation.status === "PENDING_ADVISOR" && !conversation.assigned_advisor_id;
  // Abierto por defecto solo si nadie tomó el caso (ahí el asesor necesita todo para decidir);
  // controlado para que un re-render del sondeo no revierta lo que el asesor plegó/abrió.
  const [open, setOpen] = useState(untaken);
  return (
    <div className="flex flex-col gap-2.5 lg:hidden">
      {conversation.handoff_reason && (
        <div className="rounded-xl bg-[color:var(--vmc-color-orange-600)]/10 px-3.5 py-2.5">
          <p className="text-[11px] font-bold uppercase tracking-wide text-[#9A4A0F]">Derivación</p>
          <p className="mt-0.5 text-sm text-[#9A4A0F]">{handoffReasonLabel(conversation.handoff_reason)}</p>
          {conversation.handoff_requested_at && (
            <p className="mt-0.5 text-xs text-[#9A4A0F]/80">
              Esperando hace {formatWaitTime(conversation.handoff_requested_at, now)}
            </p>
          )}
        </div>
      )}
      <details
        className="group rounded-xl border border-black/5"
        open={open}
        onToggle={(e) => setOpen(e.currentTarget.open)}
      >
        <summary className="flex cursor-pointer list-none items-center justify-between gap-2 px-3.5 py-2.5 text-xs font-bold uppercase tracking-wide text-neutral-500">
          Detalles del caso
          <ChevronRightIcon
            width={14}
            height={14}
            className="text-neutral-400 transition-transform group-open:rotate-90"
          />
        </summary>
        <div className="border-t border-black/5 px-3.5 py-2.5">
          {/* Mismo orden que el <aside> de desktop (D-010): el CUU primero, es el código
              que el usuario ve en VMC y dice por teléfono. */}
          <dl className="space-y-1.5 text-sm">
            <Field label="CUU" value={conversation.user_cuu} />
            <Field label="Correo" value={conversation.user_email} />
            <Field label="ID VMC" value={conversation.user_id} />
            <Field label="Nombre" value={conversation.user_name} />
            <Field label="Empresa" value={conversation.user_company} />
          </dl>
          <p className="mt-2.5 rounded-lg bg-[color:var(--vmc-color-vault-500)]/5 p-2.5 text-sm text-neutral-700">
            <span className="font-semibold text-[color:var(--vmc-color-vault-700)]">Resumen IA: </span>
            {conversation.summary ?? "Sin resumen todavía."}
          </p>
        </div>
      </details>
    </div>
  );
}
