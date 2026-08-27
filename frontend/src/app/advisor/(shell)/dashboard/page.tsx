import Link from "next/link";
import Table from "@/concorde/components/Table";
import Button from "@/concorde/components/Button";
import AvatarZone from "@/concorde/components/AvatarZone";
import StatCard from "@/components/StatCard";
import StatusBadge from "@/components/StatusBadge";
import { MOCK_CONVERSATIONS } from "@/lib/mock-data";
import { formatWaitTime, MOCK_NOW_MS, STATUS_LABEL } from "@/lib/format";
import type { ConversationStatus } from "@/lib/types";

/**
 * Dashboard operativo (RF-047/048). D-013 sigue abierta: este es el set mínimo que el spec
 * ya pide (volumen, pendientes, en atención, cerrados, espera) — nada de costos IA ni panel de
 * configuración (RF-049, fuera de alcance del MVP).
 */

const STATUSES: ConversationStatus[] = ["PENDING_ADVISOR", "IN_ATTENTION", "BOT_ATTENDING", "CLOSED"];

const BAR_COLOR: Record<ConversationStatus, string> = {
  PENDING_ADVISOR: "#ED8936",
  IN_ATTENTION: "#00AEB1",
  BOT_ATTENDING: "#8460E5",
  CLOSED: "#C7C9CC",
};

export default function DashboardPage() {
  const total = MOCK_CONVERSATIONS.length;
  const countByStatus = Object.fromEntries(
    STATUSES.map((status) => [status, MOCK_CONVERSATIONS.filter((c) => c.status === status).length]),
  ) as Record<ConversationStatus, number>;

  const handoffs = MOCK_CONVERSATIONS.filter((c) => c.handoff_requested_at !== null);
  const pending = MOCK_CONVERSATIONS.filter((c) => c.status === "PENDING_ADVISOR");
  const avgWaitMinutes =
    pending.length === 0
      ? null
      : Math.round(
          pending.reduce(
            (sum, c) => sum + (MOCK_NOW_MS - new Date(c.handoff_requested_at as string).getTime()) / 60_000,
            0,
          ) / pending.length,
        );

  const recent = [...MOCK_CONVERSATIONS].sort((a, b) => (a.last_message_at < b.last_message_at ? 1 : -1));

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-bold text-[#191C1C]">Dashboard operativo</h1>
        <p className="mt-1 text-sm text-[#9A4A0F]">
          Borrador — el set exacto de métricas y ventanas de tiempo está pendiente de D-013.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-6">
        <StatCard label="Conversaciones" value={String(total)} />
        <StatCard label="Pendientes" value={String(countByStatus.PENDING_ADVISOR)} />
        <StatCard label="En atención" value={String(countByStatus.IN_ATTENTION)} />
        <StatCard label="Cerradas" value={String(countByStatus.CLOSED)} />
        <StatCard
          label="Casos derivados"
          value={String(handoffs.length)}
          hint="Proxy de tickets — Tickets aún no existe (D-008)"
        />
        <StatCard
          label="Espera promedio"
          value={avgWaitMinutes === null ? "—" : `${avgWaitMinutes} min`}
          hint="Solo pendientes de asesor"
        />
      </div>

      <div className="rounded-2xl bg-white p-5 shadow-sm">
        <h2 className="text-sm font-bold uppercase tracking-wide text-neutral-500">
          Distribución por estado
        </h2>
        <div className="mt-3 flex h-3 overflow-hidden rounded-full bg-neutral-100">
          {STATUSES.map((status) =>
            countByStatus[status] > 0 ? (
              <div
                key={status}
                style={{ width: `${(countByStatus[status] / total) * 100}%`, background: BAR_COLOR[status] }}
                title={`${STATUS_LABEL[status]}: ${countByStatus[status]}`}
              />
            ) : null,
          )}
        </div>
        <div className="mt-3 flex flex-wrap gap-4 text-xs text-neutral-500">
          {STATUSES.map((status) => (
            <span key={status} className="flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full" style={{ background: BAR_COLOR[status] }} />
              {STATUS_LABEL[status]} ({countByStatus[status]})
            </span>
          ))}
        </div>
      </div>

      <div>
        <h2 className="mb-3 text-sm font-bold uppercase tracking-wide text-neutral-500">
          Conversaciones recientes
        </h2>
        <Table
          caption="Conversaciones recientes"
          columns={[
            { header: "Usuario" },
            { header: "Último mensaje", className: "hidden md:table-cell" },
            { header: "Estado", align: "center" },
            { header: "Espera", align: "center" },
            { header: "", align: "right" },
          ]}
          rows={recent.map((conv) => [
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
            <StatusBadge key="status" status={conv.status} />,
            <span key="wait">{formatWaitTime(conv.last_message_at, MOCK_NOW_MS)}</span>,
            <div key="open" className="flex justify-end">
              <Link href={`/advisor/conversations/${conv.conversation_id}`}>
                <Button variant="outline">Ver</Button>
              </Link>
            </div>,
          ])}
        />
      </div>
    </div>
  );
}
