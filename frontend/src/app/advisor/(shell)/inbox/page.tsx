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
  });

  return (
    <div className="flex flex-col gap-5">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold text-[#191C1C]">Bandeja de conversaciones</h1>
        <TabSelector
          options={FILTERS.map((f) => f.label)}
          value={filterIndex}
          onChange={setFilterIndex}
          aria-label="Filtrar por estado"
        />
      </div>

      <Table
        caption="Conversaciones"
        columns={[
          { header: "Usuario" },
          { header: "Último mensaje" },
          { header: "Espera", align: "center" },
          { header: "Canal", align: "center" },
          { header: "Estado", align: "center" },
          { header: "Asesor" },
          { header: "No leídos", align: "center" },
          { header: "", align: "right" },
        ]}
        rows={conversations.map((conv) => [
          <div key="user" className="flex items-center gap-3">
            <AvatarZone size="sm" title={conv.user_name ?? "Anónimo"} />
            <div>
              <p className="font-semibold text-[#191C1C]">{conv.user_name ?? "Anónimo"}</p>
              {conv.user_id && <p className="text-xs text-neutral-400">{conv.user_id}</p>}
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
            className={conv.unread_count > 0 ? "font-bold text-[#ED8936]" : "text-neutral-400"}
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
    </div>
  );
}
