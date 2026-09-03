import Link from "next/link";
import QueueRow from "@/components/QueueRow";
import StatusBadge from "@/components/StatusBadge";
import { CURRENT_ADVISOR, MOCK_CONVERSATIONS } from "@/lib/mock-data";
import { MOCK_NOW_MS, STATUS_LABEL } from "@/lib/format";
import type { ConversationStatus } from "@/lib/types";

/**
 * Dashboard operativo del asesor (RF-047/048): qué atender ahora — la cola de hoy, no un
 * histórico. El rendimiento de la IA (costo, RAG, intents) responde otra pregunta, la de negocio
 * (Silvana/Julio), no la de quien atiende la bandeja — se sacó de aquí (ver
 * ANALISIS-METRICAS-DASHBOARD.md, D-013) en vez de mostrarle a un asesor datos que no le sirven
 * para su turno.
 *
 * Mismo esqueleto que la bandeja (inbox/layout.tsx + inbox/[id]/page.tsx): panel flexible +
 * aside fijo de 320px, cada uno UNA sola card (rounded-2xl bg-white shadow-sm) con header propio
 * y filas divididas por dentro — no un mosaico de tiles sueltos, cada uno con su propia sombra.
 * `QueueRow`/`StatusBadge` se reusan tal cual (mismo componente, no una reinterpretación) para
 * que "el caso que más espera" y "mis casos en atención" se vean idénticos a como se ven ahí.
 */

const STATUSES: ConversationStatus[] = ["PENDING_ADVISOR", "IN_ATTENTION", "BOT_ATTENDING", "CLOSED"];

const BAR_COLOR: Record<ConversationStatus, string> = {
  PENDING_ADVISOR: "#ED8936",
  IN_ATTENTION: "#00AEB1",
  BOT_ATTENDING: "#8460E5",
  // Mismo tono que StatusBadge.DOT_COLOR.CLOSED — antes decía #C7C9CC, un gris inventado aparte.
  CLOSED: "#99A1AF",
};

/** Mismo tono oscuro que StatusBadge usa como texto — el único seguro en contraste sobre blanco. */
const DEEP_COLOR: Record<ConversationStatus, string> = {
  PENDING_ADVISOR: "#9A4A0F",
  IN_ATTENTION: "#00696B",
  BOT_ATTENDING: "#3B1782",
  CLOSED: "#5C6266",
};

const FILTER_PARAM: Record<ConversationStatus, string> = {
  PENDING_ADVISOR: "pendientes",
  IN_ATTENTION: "atencion",
  BOT_ATTENDING: "todas",
  CLOSED: "cerradas",
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

  const presentStatuses = STATUSES.filter((s) => countByStatus[s] > 0);

  const myOpenCases = MOCK_CONVERSATIONS.filter(
    (c) => c.assigned_advisor_id === CURRENT_ADVISOR.advisor_id && c.status === "IN_ATTENTION",
  );

  // Mismo criterio que "Más urgente" en la bandeja (inbox/layout.tsx): el pendiente con el
  // last_message_at más antiguo — quien lleva más tiempo esperando, no el primero de la lista.
  const mostUrgent = [...pending].sort((a, b) => a.last_message_at.localeCompare(b.last_message_at))[0] ?? null;

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 lg:h-full lg:flex-row lg:overflow-hidden">
      <section className="flex min-h-0 min-w-0 flex-1 flex-col rounded-2xl bg-white shadow-sm">
        <header className="flex items-center justify-between gap-3 border-b border-black/5 px-5 py-4">
          <div>
            <h2 className="text-base font-semibold text-[#191C1C]">Cola de hoy</h2>
            <p className="mt-0.5 text-sm text-neutral-500">Qué atender ahora, no un histórico.</p>
          </div>
          <Link
            href="/advisor/inbox"
            className="flex-shrink-0 rounded-full border border-neutral-200 px-3 py-1.5 text-xs font-semibold text-neutral-500 transition hover:border-neutral-300 hover:text-neutral-700"
          >
            Ver bandeja
          </Link>
        </header>

        <div className="flex min-h-0 flex-1 flex-col divide-y divide-black/5 overflow-y-auto">
          <Link
            href="/advisor/inbox?estado=pendientes"
            className="flex items-center justify-between gap-4 px-5 py-5 transition hover:bg-neutral-50"
          >
            <div>
              <p className="flex items-center gap-2 text-xs font-bold uppercase tracking-wide text-neutral-500">
                <span className="relative flex h-2 w-2">
                  {countByStatus.PENDING_ADVISOR > 0 && (
                    <span
                      className="absolute inline-flex h-full w-full rounded-full opacity-75 motion-safe:animate-ping"
                      style={{ background: BAR_COLOR.PENDING_ADVISOR }}
                    />
                  )}
                  <span className="relative inline-flex h-2 w-2 rounded-full" style={{ background: BAR_COLOR.PENDING_ADVISOR }} />
                </span>
                Pendientes de asesor
              </p>
              <p className="mt-1 text-sm text-neutral-500">
                {countByStatus.PENDING_ADVISOR > 0 ? "Nadie los ha tomado todavía" : "La cola está al día"}
              </p>
            </div>
            <p
              className="flex-shrink-0 text-5xl font-bold leading-none tracking-tight"
              style={{ color: countByStatus.PENDING_ADVISOR > 0 ? DEEP_COLOR.PENDING_ADVISOR : "#191C1C" }}
            >
              {countByStatus.PENDING_ADVISOR}
            </p>
          </Link>

          <div className="flex flex-col divide-y divide-black/5 sm:flex-row sm:divide-x sm:divide-y-0">
            <div className="flex flex-1 flex-col justify-center gap-1 px-5 py-4">
              <p className="text-xs font-bold uppercase tracking-wide text-neutral-500">Espera promedio</p>
              <p
                className="text-3xl font-bold leading-none tracking-tight"
                style={{ color: avgWaitMinutes !== null ? DEEP_COLOR.PENDING_ADVISOR : "#191C1C" }}
              >
                {avgWaitMinutes === null ? "—" : `${avgWaitMinutes} min`}
              </p>
              <p className="text-xs text-neutral-500">Solo casos pendientes de asesor</p>
            </div>
            <div className="flex flex-1 flex-col justify-center">
              {mostUrgent ? (
                <QueueRow conversation={mostUrgent} active={false} mostUrgent now={MOCK_NOW_MS} isMine={false} />
              ) : (
                <p className="px-5 py-4 text-sm text-neutral-500">Nadie está esperando en la cola ahora.</p>
              )}
            </div>
          </div>

          <div className="px-5 py-4">
            <div className="flex items-baseline justify-between gap-2">
              <h3 className="text-xs font-bold uppercase tracking-wide text-neutral-500">Distribución</h3>
              <Link href="/advisor/inbox" className="text-xs font-semibold text-neutral-500 transition hover:text-[#191C1C]">
                {total} · {handoffs.length} deriv.
              </Link>
            </div>
            <div
              className="mt-3 grid h-3 gap-1"
              style={{ gridTemplateColumns: presentStatuses.map((s) => `${countByStatus[s]}fr`).join(" ") }}
            >
              {presentStatuses.map((status) => (
                <Link
                  key={status}
                  href={`/advisor/inbox?estado=${FILTER_PARAM[status]}`}
                  style={{ background: BAR_COLOR[status] }}
                  title={`${STATUS_LABEL[status]}: ${countByStatus[status]}`}
                  className="rounded-full transition hover:brightness-110"
                />
              ))}
            </div>
            <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-4">
              {STATUSES.map((status) => (
                <Link
                  key={status}
                  href={`/advisor/inbox?estado=${FILTER_PARAM[status]}`}
                  className="flex items-center justify-between gap-2 transition hover:opacity-80"
                >
                  <StatusBadge status={status} />
                  <span className="text-sm font-bold" style={{ color: DEEP_COLOR[status] }}>
                    {countByStatus[status]}
                  </span>
                </Link>
              ))}
            </div>
          </div>
        </div>
      </section>

      <aside className="flex min-h-0 w-full flex-shrink-0 flex-col gap-4 rounded-2xl bg-white p-5 shadow-sm lg:w-80">
        <div className="flex-shrink-0">
          <h2 className="text-xs font-bold uppercase tracking-wide text-neutral-500">Mi turno</h2>
          <p className="mt-2.5 flex items-baseline gap-2">
            <span
              className="text-5xl font-bold leading-none tracking-tight"
              style={{ color: myOpenCases.length > 0 ? DEEP_COLOR.IN_ATTENTION : "#191C1C" }}
            >
              {myOpenCases.length}
            </span>
            <span className="text-sm text-neutral-500">
              {myOpenCases.length === 1 ? "caso en atención" : "casos en atención"}
            </span>
          </p>
        </div>

        <div className="flex min-h-0 flex-1 flex-col divide-y divide-black/5 overflow-y-auto">
          {myOpenCases.length === 0 ? (
            <p className="py-3 text-sm text-neutral-500">Nada asignado a ti ahora mismo.</p>
          ) : (
            myOpenCases.map((conv) => (
              <QueueRow key={conv.conversation_id} conversation={conv} active={false} now={MOCK_NOW_MS} isMine />
            ))
          )}
        </div>
      </aside>
    </div>
  );
}
