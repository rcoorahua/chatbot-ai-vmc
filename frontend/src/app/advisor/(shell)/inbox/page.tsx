import Link from "next/link";
import Button from "@/concorde/components/Button";
import { MOCK_CONVERSATIONS } from "@/lib/mock-data";
import { formatWaitTime, MOCK_NOW_MS } from "@/lib/format";

/**
 * Estado del cockpit sin caso seleccionado (solo visible en desktop — en mobile
 * el rail ocupa toda la pantalla, ver layout.tsx). Atajo directo al caso más
 * urgente en vez de un vacío mudo.
 */
export default function InboxHomePage() {
  const mostUrgent = [...MOCK_CONVERSATIONS]
    .filter((c) => c.status === "PENDING_ADVISOR")
    .sort((a, b) => a.last_message_at.localeCompare(b.last_message_at))[0];

  return (
    <div className="flex flex-1 flex-col items-center justify-center rounded-2xl bg-white p-10 text-center shadow-sm">
      {mostUrgent ? (
        <>
          <p className="text-xs font-bold uppercase tracking-wide text-neutral-400">
            El caso más urgente ahora
          </p>
          <p className="mt-2 text-lg font-bold text-[#191C1C]">
            {mostUrgent.user_name ?? "Anónimo"} · esperando{" "}
            {formatWaitTime(mostUrgent.last_message_at, MOCK_NOW_MS)}
          </p>
          <p className="mt-1 max-w-sm text-sm text-neutral-500">{mostUrgent.last_message_preview}</p>
          <Link href={`/advisor/inbox/${mostUrgent.conversation_id}`} className="mt-5">
            <Button variant="secondary-sm">Abrir caso</Button>
          </Link>
          <p className="mt-6 text-xs text-neutral-400">o elige cualquier caso de la cola</p>
        </>
      ) : (
        <p className="text-sm text-neutral-500">No hay casos pendientes ahora mismo — elige uno de la cola.</p>
      )}
    </div>
  );
}
