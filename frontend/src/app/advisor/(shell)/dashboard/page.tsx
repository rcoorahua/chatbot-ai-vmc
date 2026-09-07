"use client";

import { useEffect, useState } from "react";
import { apiErrorMessage, getConversations, getTickets } from "@/lib/api";
import { STATUS_BG, STATUS_COLOR, STATUS_DEEP_COLOR } from "@/lib/status-colors";
import { useAdvisor } from "@/lib/advisor-context";
import { STATUS_LABEL } from "@/lib/format";
import type { Conversation, ConversationStatus, Ticket } from "@/lib/types";

/**
 * Dashboard del KAM (RF-047/048). Dos cards gemelas con el lenguaje visual de la Bandeja
 * (card `rounded-2xl bg-white shadow-sm`, tokens `lib/status-colors`) pero **visual**: un
 * gráfico arriba y una grilla de tiles con el número grande y fondo teñido por estado.
 *
 *  - "Resumen del turno": barra apilada del estado de la cola (bot / pendiente / en atención,
 *    sin CLOSED: eso no está en cola) + 6 tiles del turno.
 *  - "Mi rendimiento": barras de flujo del día (recibidos vs cerrados) + 6 tiles propios.
 *
 * Fuentes: `GET /advisor/conversations` (4 estados) + `GET /advisor/tickets` (abiertos y
 * cerrados) — prioridad, `classification_source` (indicador D-008), `missing_data` (RF-024),
 * `resolution` (RF-050) y el `closed_by` REAL del asesor. Semana/mes y el tiempo de primera
 * respuesta siguen necesitando un endpoint de agregación (D-013).
 *
 * Los 3 colores de la barra apilada pasan el validador de dataviz (CVD ΔE 15.3); el gris de
 * CLOSED no, por eso CLOSED queda fuera del gráfico (y tampoco es "cola").
 */

const STATUSES: ConversationStatus[] = ["PENDING_ADVISOR", "IN_ATTENTION", "BOT_ATTENDING", "CLOSED"];
const QUEUE_STATES: ConversationStatus[] = ["BOT_ATTENDING", "PENDING_ADVISOR", "IN_ATTENTION"];

// ponytail: umbrales fijos aquí; a `config` cuando D-013 cierre (los define Silvana/Julio).
const INK = "#191c1c";
const WAIT_ALERT_MIN = 30;
const ESCALATION_ALERT_PCT = 50;

type Tone = "alert" | "ok" | "neutral";

function fmtMins(m: number | null): string {
  if (m === null) return "—";
  const r = Math.round(m);
  if (r < 60) return `${r} min`;
  const h = Math.floor(r / 60);
  const rest = r % 60;
  return rest === 0 ? `${h} h` : `${h} h ${rest} min`;
}

// ── Piezas visuales ──────────────────────────────────────────────────────────

/** Barra 100% apilada + leyenda con etiqueta y conteo (relief para el WARN de contraste). */
function StackBar({ segments }: { segments: { label: string; value: number; color: string }[] }) {
  const shown = segments.filter((s) => s.value > 0);
  return (
    <div>
      <div className="flex h-3.5 w-full gap-0.5">
        {(shown.length ? shown : [{ label: "—", value: 1, color: "#e5e5e5" }]).map((s) => (
          <div
            key={s.label}
            className="min-w-[4px] rounded-full"
            style={{ flexGrow: s.value, background: s.color }}
            title={`${s.label}: ${s.value}`}
          />
        ))}
      </div>
      <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5">
        {segments.map((s) => (
          <li key={s.label} className="flex items-center gap-1.5 text-xs">
            <span className="h-2 w-2 flex-shrink-0 rounded-full" style={{ background: s.color }} />
            <span className="text-neutral-600">{s.label}</span>
            <span className="font-bold tabular-nums text-[#191C1C]">{s.value}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Barras horizontales de una sola serie a escala común (el título nombra la serie). */
function MiniBars({ rows, color }: { rows: { label: string; value: number }[]; color: string }) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  return (
    <ul className="flex flex-col gap-2.5">
      {rows.map((r) => (
        <li key={r.label} className="flex items-center gap-3 text-xs">
          <span className="w-28 flex-shrink-0 text-neutral-600">{r.label}</span>
          <span className="h-2.5 flex-1 rounded-full bg-neutral-100">
            <span
              className="block h-full rounded-full"
              style={{ width: `${(r.value / max) * 100}%`, minWidth: r.value > 0 ? "6px" : 0, background: color }}
            />
          </span>
          <span className="w-5 flex-shrink-0 text-right font-bold tabular-nums text-[#191C1C]">{r.value}</span>
        </li>
      ))}
    </ul>
  );
}

function StatTile({ value, label, hint, tone }: { value: string; label: string; hint: string; tone: Tone }) {
  const bg = tone === "alert" ? STATUS_BG.PENDING_ADVISOR : tone === "ok" ? STATUS_BG.IN_ATTENTION : "#ffffff";
  const num =
    tone === "alert" ? STATUS_DEEP_COLOR.PENDING_ADVISOR : tone === "ok" ? STATUS_DEEP_COLOR.IN_ATTENTION : INK;
  return (
    <div className="flex flex-col justify-between gap-3 px-4 py-4" style={{ background: bg }}>
      <p className="text-3xl font-bold leading-none tracking-[-0.03em] tabular-nums" style={{ color: num }}>
        {value}
      </p>
      <div>
        <p className="text-xs font-bold uppercase tracking-wide text-neutral-500">{label}</p>
        <p className="mt-0.5 text-xs leading-snug text-neutral-500">{hint}</p>
      </div>
    </div>
  );
}

function Card({
  title,
  subtitle,
  chart,
  tiles,
  note,
}: {
  title: string;
  subtitle: string;
  chart: React.ReactNode;
  tiles: { value: string; label: string; hint: string; tone: Tone }[];
  note: string;
}) {
  return (
    <section className="flex w-full min-w-0 flex-1 flex-col overflow-hidden rounded-2xl bg-white shadow-sm">
      <div className="border-b border-black/5 px-4 py-3">
        <h2 className="text-xs font-bold uppercase tracking-wide text-neutral-500">{title}</h2>
        <p className="mt-1 text-xs text-neutral-500">{subtitle}</p>
      </div>
      <div className="px-4 py-4">{chart}</div>
      <div className="grid flex-1 grid-cols-2 gap-px border-t border-black/5 bg-black/5 sm:grid-cols-3">
        {tiles.map((t) => (
          <StatTile key={t.label} {...t} />
        ))}
      </div>
      <p className="border-t border-black/5 px-4 py-2.5 text-[11px] text-neutral-500">{note}</p>
    </section>
  );
}

// ── Página ───────────────────────────────────────────────────────────────────

export default function DashboardPage() {
  const { advisor } = useAdvisor();
  const [now] = useState(() => Date.now());
  type Loaded = { conversations: Conversation[]; openTickets: Ticket[]; closedTickets: Ticket[] };
  const [result, setResult] = useState<Loaded | { error: string } | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      Promise.all(STATUSES.map((status) => getConversations({ status, limit: 100 }))),
      getTickets({ limit: 100 }),
      getTickets({ status: "CLOSED", limit: 100 }),
    ])
      .then(([byStatus, openTickets, closedTickets]) => {
        if (!cancelled) setResult({ conversations: byStatus.flat(), openTickets, closedTickets });
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
      <div className="flex flex-col gap-4 lg:flex-row">
        <div className="h-96 flex-1 animate-pulse rounded-2xl bg-white shadow-sm" />
        <div className="h-96 flex-1 animate-pulse rounded-2xl bg-white shadow-sm" />
      </div>
    );
  }

  if ("error" in result) {
    return (
      <div className="flex flex-1 items-center justify-center rounded-2xl bg-white p-10 text-center text-sm text-[#9A4A0F] shadow-sm">
        {result.error}
      </div>
    );
  }

  const { conversations, openTickets, closedTickets } = result;
  const total = conversations.length;
  const countBy = (s: ConversationStatus) => conversations.filter((c) => c.status === s).length;

  const handoffs = conversations.filter((c) => c.handoff_requested_at !== null);
  const pending = conversations.filter((c) => c.status === "PENDING_ADVISOR");
  const escalationRate = total === 0 ? null : Math.round((handoffs.length / total) * 100);

  const waitMins = pending
    .map((c) => (now - new Date(c.handoff_requested_at as string).getTime()) / 60_000)
    .sort((a, b) => a - b);
  const percentile = (p: number): number | null =>
    waitMins.length === 0 ? null : waitMins[Math.min(waitMins.length - 1, Math.ceil((p / 100) * waitMins.length) - 1)];
  const waitP50 = percentile(50);
  const waitP90 = percentile(90);

  const unattended = conversations.filter((c) => c.unread_count > 0).length;

  const convsByUser = new Map<string, number>();
  for (const c of conversations) if (c.user_id) convsByUser.set(c.user_id, (convsByUser.get(c.user_id) ?? 0) + 1);
  const repeatUsers = [...convsByUser.values()].filter((n) => n > 1).length;

  const openHigh = openTickets.filter((t) => t.priority === "HIGH").length;
  const unconfirmed = openTickets.filter((t) => t.classification_source === "RULES").length;

  const meId = advisor?.advisor_id;
  const today = new Date(now).toDateString();
  const isToday = (iso: string | null | undefined): boolean => !!iso && new Date(iso).toDateString() === today;

  const myClosedToday = closedTickets.filter((t) => t.closed_by === meId && isToday(t.closed_at));
  const closedToday = myClosedToday.length;
  const closedNoResolution = myClosedToday.filter((t) => !t.resolution).length;
  const inAttention = conversations.filter((c) => c.status === "IN_ATTENTION" && c.assigned_advisor_id === meId).length;
  const receivedToday = conversations.filter(
    (c) => c.assigned_advisor_id === meId && isToday(c.handoff_requested_at),
  ).length;
  const myMissingData = openTickets.filter(
    (t) => t.assigned_advisor_id === meId && t.missing_data.length > 0,
  ).length;
  const myUnread = conversations.filter(
    (c) => c.status === "IN_ATTENTION" && c.assigned_advisor_id === meId && c.unread_count > 0,
  ).length;

  const turnoTiles: { value: string; label: string; hint: string; tone: Tone }[] = [
    {
      value: escalationRate === null ? "—" : `${escalationRate}%`,
      label: "Escalado",
      hint: `${handoffs.length} de ${total} a un asesor`,
      tone: escalationRate !== null && escalationRate >= ESCALATION_ALERT_PCT ? "alert" : "neutral",
    },
    {
      value: fmtMins(waitP50),
      label: "Espera mediana",
      hint: `p90 ${fmtMins(waitP90)}`,
      tone: waitP50 !== null && waitP50 >= WAIT_ALERT_MIN ? "alert" : "neutral",
    },
    {
      value: String(openTickets.length),
      label: "Tickets abiertos",
      hint: openHigh > 0 ? `${openHigh} de prioridad alta` : "Sin prioridad alta",
      tone: openHigh > 0 ? "alert" : "neutral",
    },
    {
      value: String(unconfirmed),
      label: "Sin confirmar",
      hint: "Clasificación sin revisar",
      tone: unconfirmed > 0 ? "alert" : "neutral",
    },
    { value: String(unattended), label: "Sin leer", hint: "Nadie abrió el último", tone: unattended > 0 ? "alert" : "neutral" },
    { value: String(repeatUsers), label: "Reincidencia", hint: "Con más de una conversación", tone: "neutral" },
  ];

  const rendimientoTiles: { value: string; label: string; hint: string; tone: Tone }[] = [
    { value: String(closedToday), label: "Cerrados hoy", hint: "Los cerraste tú", tone: closedToday > 0 ? "ok" : "neutral" },
    { value: String(inAttention), label: "En atención", hint: "Asignados a ti ahora", tone: "neutral" },
    { value: String(receivedToday), label: "Recibidos hoy", hint: "Te llegaron por derivación", tone: "neutral" },
    {
      value: String(myMissingData),
      label: "Datos pendientes",
      hint: "Info que aún debes pedir",
      tone: myMissingData > 0 ? "alert" : "neutral",
    },
    {
      value: String(closedNoResolution),
      label: "Sin resolución",
      hint: "Cerrados hoy sin anotar cómo",
      tone: closedNoResolution > 0 ? "alert" : "neutral",
    },
    { value: String(myUnread), label: "Sin abrir", hint: "Mensajes tuyos sin abrir", tone: myUnread > 0 ? "alert" : "neutral" },
  ];

  return (
    <div className="flex flex-col gap-4 lg:flex-row lg:items-stretch">
      <Card
        title="Resumen del turno"
        subtitle="Estado de la cola ahora · todo el equipo"
        chart={
          <StackBar
            segments={QUEUE_STATES.map((s) => ({
              label: STATUS_LABEL[s],
              value: countBy(s),
              color: STATUS_COLOR[s],
            }))}
          />
        }
        tiles={turnoTiles}
        note="Bandeja + tickets abiertos · máx. 100 por consulta · taxonomía provisional (D-008)"
      />
      <Card
        title="Mi rendimiento"
        subtitle={`Hoy${advisor?.name ? ` · ${advisor.name}` : ""}`}
        chart={
          <MiniBars
            color={STATUS_COLOR.IN_ATTENTION}
            rows={[
              { label: "Recibidos hoy", value: receivedToday },
              { label: "En atención", value: inAttention },
              { label: "Cerrados hoy", value: closedToday },
            ]}
          />
        }
        tiles={rendimientoTiles}
        note="Solo del día · semana y mes necesitan un endpoint de métricas (D-013)"
      />
    </div>
  );
}
