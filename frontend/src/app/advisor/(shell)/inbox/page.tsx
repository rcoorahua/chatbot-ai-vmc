"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import Button from "@/concorde/components/Button";
import { apiErrorMessage, getConversations } from "@/lib/api";
import { formatWaitTime } from "@/lib/format";
import type { Conversation } from "@/lib/types";

/**
 * Estado del cockpit sin caso seleccionado (solo visible en desktop — en mobile
 * el rail ocupa toda la pantalla, ver layout.tsx). Atajo directo al caso más
 * urgente en vez de un vacío mudo.
 */
export default function InboxHomePage() {
  const [now] = useState(() => Date.now());
  const [result, setResult] = useState<{ conversations: Conversation[] } | { error: string } | null>(null);

  useEffect(() => {
    let cancelled = false;
    getConversations({ status: "PENDING_ADVISOR", limit: 100 })
      .then((conversations) => {
        if (!cancelled) setResult({ conversations });
      })
      .catch((err: unknown) => {
        if (!cancelled) setResult({ error: apiErrorMessage(err) });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!result) {
    return (
      <div className="h-full min-h-[16rem] flex-1 animate-pulse rounded-2xl bg-white shadow-sm" />
    );
  }

  if ("error" in result) {
    return (
      <div className="flex flex-1 items-center justify-center rounded-2xl bg-white p-10 text-center text-sm text-[#9A4A0F] shadow-sm">
        {result.error}
      </div>
    );
  }

  const mostUrgent = [...result.conversations].sort((a, b) =>
    a.last_message_at.localeCompare(b.last_message_at),
  )[0];

  return (
    <div className="flex flex-1 flex-col items-center justify-center rounded-2xl bg-white p-10 text-center shadow-sm">
      {mostUrgent ? (
        <>
          <p className="text-xs font-bold uppercase tracking-wide text-neutral-400">
            El caso más urgente ahora
          </p>
          <p className="mt-2 text-lg font-bold text-[#191C1C]">
            {mostUrgent.user_name ?? "Anónimo"} · esperando{" "}
            {formatWaitTime(mostUrgent.last_message_at, now)}
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
