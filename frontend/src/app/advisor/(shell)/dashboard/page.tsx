"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiErrorMessage, getConversations } from "@/lib/api";
import { STATUS_COLOR, STATUS_DEEP_COLOR } from "@/lib/status-colors";
import { useAdvisor } from "@/lib/advisor-context";
import type { Conversation, ConversationStatus } from "@/lib/types";

/**
 * Dashboard del KAM (RF-047/048). Dos cards gemelas —mismo ancho, mismo alto, misma lista de
 * 4 filas— con el lenguaje visual de la Bandeja: card `rounded-2xl bg-white shadow-sm`,
 * cabecera en versalitas como "COLA DE CASOS", filas tipo `QueueRow` (punto de estado +
 * etiqueta + valor a la derecha) y la paleta compartida `lib/status-colors`.
 *
 *  - "Resumen del turno": estado de la cola de todo el equipo. Cada fila enlaza a su recorte.
 *  - "Mi rendimiento": lo del asesor logueado, SOLO del día. `GET /advisor/conversations`
 *    capa a 100 por estado y no hace rango de fechas → semana/mes necesitan un endpoint de
 *    métricas (D-013).
 *
 * ponytail: sin ese endpoint, `GET /advisor/conversations` es LA BANDEJA (`service.list_inbox`):
 * sin `status` solo trae PENDING_ADVISOR + IN_ATTENTION, así que se piden los 4 estados por
 * separado (100 c/u) y se mezclan. "Quién cerró" se aproxima con `assigned_advisor_id` porque
 * `closed_by` solo distingue ADVISOR de AUTO, no a la persona.
 */

const STATUSES: ConversationStatus[] = ["PENDING_ADVISOR", "IN_ATTENTION", "BOT_ATTENDING", "CLOSED"];

// Semántica del dashboard sobre la paleta de estados compartida (lib/status-colors, auditoría
// 2026-09-06): atención = el naranja de "pendiente", ok = el teal de "en atención", neutro =
// el gris de "cerrada". El DS no tiene un rojo de alarma.
// ponytail: umbrales fijos aquí; a `config` cuando D-013 cierre (los define Silvana/Julio).
const DOT_ALERT = STATUS_COLOR.PENDING_ADVISOR;
const DOT_OK = STATUS_COLOR.IN_ATTENTION;
const DOT_NEUTRAL = STATUS_COLOR.CLOSED;
const VALUE_ALERT = STATUS_DEEP_COLOR.PENDING_ADVISOR;
const INK = "#191c1c"; // = --foreground
const WAIT_ALERT_MIN = 30;
const ESCALATION_ALERT_PCT = 50;

function fmtMins(m: number | null): string {
  if (m === null) return "—";
  const r = Math.round(m);
  if (r < 60) return `${r} min`;
  const h = Math.floor(r / 60);
  const rest = r % 60;
  return rest === 0 ? `${h} h` : `${h} h ${rest} min`;
}

type RowData = {
  value: string;
  label: string;
  hint: string;
  alert: boolean;
  ok?: boolean;
  href?: string;
};

/** Misma estructura que `QueueRow`: punto de estado + cuerpo, valor donde va el timestamp. */
function Row({ value, label, hint, alert, ok, href }: RowData) {
  const dot = alert ? DOT_ALERT : ok ? DOT_OK : DOT_NEUTRAL;
  const body = (
    <>
      <span className="mt-1.5 h-2 w-2 flex-shrink-0 rounded-full" style={{ background: dot }} aria-hidden />
      <span className="min-w-0 flex-1">
        <span className="flex items-center justify-between gap-3">
          <span className="truncate text-sm font-semibold text-[#191C1C]">{label}</span>
          <span
            className="flex-shrink-0 text-lg font-bold leading-none tracking-[-0.02em] tabular-nums"
            style={{ color: alert ? VALUE_ALERT : INK }}
          >
            {value}
          </span>
        </span>
        <span className="mt-0.5 block text-xs text-neutral-500">{hint}</span>
      </span>
    </>
  );
  const cls =
    "flex items-start gap-3 px-3 py-3 transition focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[color:var(--vmc-color-vault-500)]";
  return href ? (
    <Link href={href} className={`${cls} hover:bg-neutral-50`}>
      {body}
    </Link>
  ) : (
    <div className={cls}>{body}</div>
  );
}

function Card({
  title,
  subtitle,
  rows,
  note,
}: {
  title: string;
  subtitle: string;
  rows: RowData[];
  note: string;
}) {
  return (
    <section className="flex w-full min-w-0 flex-1 flex-col overflow-hidden rounded-2xl bg-white shadow-sm">
      <div className="border-b border-black/5 px-3 py-3">
        <h2 className="text-xs font-bold uppercase tracking-wide text-neutral-500">{title}</h2>
        <p className="mt-1 text-xs text-neutral-500">{subtitle}</p>
      </div>
      <div className="flex flex-1 flex-col divide-y divide-black/5">
        {rows.map((r) => (
          <Row key={r.label} {...r} />
        ))}
      </div>
      <p className="border-t border-black/5 px-3 py-2.5 text-[11px] text-neutral-500">{note}</p>
    </section>
  );
}

export default function DashboardPage() {
  const { advisor } = useAdvisor();
  const [now] = useState(() => Date.now());
  const [result, setResult] = useState<{ conversations: Conversation[] } | { error: string } | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all(STATUSES.map((status) => getConversations({ status, limit: 100 })))
      .then((byStatus) => {
        if (!cancelled) setResult({ conversations: byStatus.flat() });
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
        <div className="h-72 flex-1 animate-pulse rounded-2xl bg-white shadow-sm" />
        <div className="h-72 flex-1 animate-pulse rounded-2xl bg-white shadow-sm" />
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

  const { conversations } = result;
  const total = conversations.length;

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

  const unattended = conversations.filter((c) => c.unread_count > 0);

  const convsByUser = new Map<string, number>();
  for (const c of conversations) {
    if (c.user_id) convsByUser.set(c.user_id, (convsByUser.get(c.user_id) ?? 0) + 1);
  }
  const repeatUsers = [...convsByUser.values()].filter((n) => n > 1).length;

  // ── Mi rendimiento (hoy) — solo del asesor logueado ──────────────────────────
  const today = new Date(now).toDateString();
  const isToday = (iso: string | null | undefined): boolean => !!iso && new Date(iso).toDateString() === today;
  const mine = (c: Conversation): boolean => c.assigned_advisor_id === advisor?.advisor_id;

  const closedToday = conversations.filter((c) => c.status === "CLOSED" && mine(c) && isToday(c.closed_at)).length;
  const inAttention = conversations.filter((c) => c.status === "IN_ATTENTION" && mine(c)).length;
  const receivedToday = conversations.filter((c) => mine(c) && isToday(c.handoff_requested_at)).length;
  const myUnread = conversations.filter(
    (c) => c.status === "IN_ATTENTION" && mine(c) && c.unread_count > 0,
  ).length;

  const turno: RowData[] = [
    {
      value: escalationRate === null ? "—" : `${escalationRate}%`,
      label: "Escalado a un asesor",
      hint: `${handoffs.length} de ${total} conversaciones`,
      alert: escalationRate !== null && escalationRate >= ESCALATION_ALERT_PCT,
      href: "/advisor/inbox?estado=asesor",
    },
    {
      value: fmtMins(waitP50),
      label: "Espera mediana",
      hint: `p90 ${fmtMins(waitP90)}`,
      alert: waitP50 !== null && waitP50 >= WAIT_ALERT_MIN,
      href: "/advisor/inbox?estado=asesor&sub=pendientes",
    },
    {
      value: String(unattended.length),
      label: "Sin leer",
      hint: "Nadie abrió el último mensaje",
      alert: unattended.length > 0,
      href: "/advisor/inbox?estado=asesor",
    },
    {
      value: String(repeatUsers),
      label: "Reincidencia",
      hint: "Volvieron con otra conversación",
      alert: false,
      ok: repeatUsers > 0,
      href: "/advisor/inbox",
    },
  ];

  const rendimiento: RowData[] = [
    { value: String(closedToday), label: "Cerrados hoy", hint: "Que estaban asignados a ti", alert: false, ok: closedToday > 0 },
    { value: String(inAttention), label: "En atención", hint: "Asignados a ti ahora", alert: false, ok: inAttention > 0 },
    { value: String(receivedToday), label: "Recibidos hoy", hint: "Te llegaron por derivación", alert: false, ok: receivedToday > 0 },
    { value: String(myUnread), label: "Sin abrir", hint: "Mensajes en tus casos que no abriste", alert: myUnread > 0 },
  ];

  return (
    <div className="flex flex-col gap-4 lg:flex-row lg:items-stretch">
      <Card
        title="Resumen del turno"
        subtitle="Estado de la cola ahora · todo el equipo"
        rows={turno}
        note="Sobre lo visible en la bandeja · máx. 100 por estado"
      />
      <Card
        title="Mi rendimiento"
        subtitle={`Hoy${advisor?.name ? ` · ${advisor.name}` : ""}`}
        rows={rendimiento}
        note="Solo del día · semana y mes necesitan un endpoint de métricas (D-013)"
      />
    </div>
  );
}
