"use client";

import { useState } from "react";
import Link from "next/link";
import Table from "@/concorde/components/Table";
import TabSelector from "@/concorde/components/TabSelector";
import AvatarZone from "@/concorde/components/AvatarZone";
import Button from "@/concorde/components/Button";
import StatusBadge from "@/components/StatusBadge";
import { MOCK_CONVERSATIONS, CURRENT_ADVISOR } from "@/lib/mock-data";
import { formatWaitTime, MOCK_NOW_MS } from "@/lib/format";
import type { ConversationStatus } from "@/lib/types";

/**
 * Bandeja de conversaciones (RF-029/RF-032): nombre/identificador, último mensaje, tiempo de
 * espera, canal, estado, asesor asignado y contador de no leídos. "Tomar conversación" queda
 * como acción de UI; la asignación atómica (RF-029/AC-005) la resuelve el backend en F5.
 */

const FILTERS: Array<{ label: string; statuses: ConversationStatus[] | null }> = [
  { label: "Todas", statuses: null },
  { label: "Pendientes", statuses: ["PENDING_ADVISOR"] },
  { label: "En atención", statuses: ["IN_ATTENTION"] },
  { label: "Cerradas", statuses: ["CLOSED"] },
];

export default function InboxPage() {
  const [filterIndex, setFilterIndex] = useState(0);

  const conversations = MOCK_CONVERSATIONS.filter((conv) => {
    const statuses = FILTERS[filterIndex].statuses;
    return statuses === null || statuses.includes(conv.status);
  }).sort((a, b) => {
    // Sin resolver primero, y dentro de ese grupo el que espera hace más tiempo arriba
    // (el caso más urgente a la vista, no el orden arbitrario del mock).
    const aOpen = a.status !== "CLOSED";
    const bOpen = b.status !== "CLOSED";
    if (aOpen !== bOpen) return aOpen ? -1 : 1;
    return aOpen
      ? a.last_message_at.localeCompare(b.last_message_at)
      : b.last_message_at.localeCompare(a.last_message_at);
  });

  return (
    <div className="flex min-w-0 flex-col gap-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <h1 className="text-xl font-bold text-[#191C1C]">Bandeja de conversaciones</h1>
        <TabSelector
          options={FILTERS.map(
            (f) =>
              `${f.label} (${
                f.statuses === null
                  ? MOCK_CONVERSATIONS.length
                  : MOCK_CONVERSATIONS.filter((c) => f.statuses!.includes(c.status)).length
              })`,
          )}
          value={filterIndex}
          onChange={setFilterIndex}
          aria-label="Filtrar por estado"
        />
      </div>

      {conversations.length === 0 ? (
        <p className="rounded-2xl bg-white px-5 py-10 text-center text-sm text-neutral-500 shadow-sm">
          No hay conversaciones en &quot;{FILTERS[filterIndex].label}&quot; ahora mismo.
        </p>
      ) : (
      <Table
        caption="Conversaciones"
        columns={[
          { header: "Usuario" },
          { header: "Último mensaje", className: "hidden md:table-cell" },
          { header: "Espera", align: "center" },
          { header: "Canal", align: "center", className: "hidden md:table-cell" },
          { header: "Estado", align: "center" },
          { header: "Asesor", className: "hidden md:table-cell" },
          { header: "No leídos", align: "center", className: "hidden md:table-cell" },
          { header: "", align: "right" },
        ]}
        rows={conversations.map((conv) => [
          <div key="user" className="flex items-center gap-3">
            <AvatarZone size="sm" title={conv.user_name ?? "Anónimo"} />
            <div>
              <p className="font-semibold text-[#191C1C]">{conv.user_name ?? "Anónimo"}</p>
              {conv.user_id && <p className="text-xs text-neutral-500">{conv.user_id}</p>}
            </div>
          </div>,
          <span key="preview" className="line-clamp-1 max-w-xs text-neutral-600">
            {conv.last_message_preview}
          </span>,
          <span key="wait">{formatWaitTime(conv.last_message_at, MOCK_NOW_MS)}</span>,
          <span key="channel">{conv.channel}</span>,
          <StatusBadge key="status" status={conv.status} />,
          <span key="advisor">
            {conv.assigned_advisor_id
              ? conv.assigned_advisor_id === CURRENT_ADVISOR.advisor_id
                ? "Tú"
                : conv.assigned_advisor_id
              : "—"}
          </span>,
          <span
            key="unread"
            className={conv.unread_count > 0 ? "font-bold text-[#ED8936]" : "text-neutral-500"}
          >
            {conv.unread_count}
          </span>,
          <div key="action" className="flex justify-end">
            <Link href={`/advisor/conversations/${conv.conversation_id}`}>
              <Button variant={conv.status === "PENDING_ADVISOR" ? "secondary-sm" : "outline"}>
                {conv.status === "PENDING_ADVISOR" ? "Tomar conversación" : "Abrir"}
              </Button>
            </Link>
          </div>,
        ])}
      />
      )}
    </div>
  );
}
