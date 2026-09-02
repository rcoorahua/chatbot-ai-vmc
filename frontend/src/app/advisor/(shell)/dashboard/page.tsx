"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import Table from "@/concorde/components/Table";
import AvatarZone from "@/concorde/components/AvatarZone";
import StatCard from "@/components/StatCard";
import StatusBadge from "@/components/StatusBadge";
import { ChevronRightIcon } from "@/components/icons";
import { apiErrorMessage, getConversations } from "@/lib/api";
import { formatWaitTime, STATUS_LABEL } from "@/lib/format";
import type { Conversation, ConversationStatus } from "@/lib/types";

/**
 * Dashboard operativo (RF-047/048). D-013 sigue abierta: este es el set mínimo que el spec
 * ya pide (volumen, pendientes, en atención, cerrados, espera) — nada de costos IA ni panel de
 * configuración (RF-049, fuera de alcance del MVP).
 *
 * Una sola columna, de arriba a abajo — se probó un layout de contenido+rail fijo y resultó
 * confuso; el escaneo vertical simple es lo que de verdad es fácil de usar acá.
 *
 * ponytail: sin endpoint de métricas (D-013 abierta) y sin filtro, `GET /advisor/conversations`
 * es LA BANDEJA (`service.list_inbox`): sin `status` solo trae PENDING_ADVISOR + IN_ATTENTION,
 * nunca BOT_ATTENDING/CLOSED. Para un total real hay que pedir los 4 estados por separado y
 * mezclar (100 c/u, tope real del backend). Subir esto a un agregado real cuando D-013 cierre.
 */

const STATUSES: ConversationStatus[] = ["PENDING_ADVISOR", "IN_ATTENTION", "BOT_ATTENDING", "CLOSED"];

const BAR_COLOR: Record<ConversationStatus, string> = {
  PENDING_ADVISOR: "#ED8936",
  IN_ATTENTION: "#00AEB1",
  BOT_ATTENDING: "#8460E5",
  CLOSED: "#C7C9CC",
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
      <div className="flex flex-col gap-3">
        <div className="h-24 animate-pulse rounded-2xl bg-white shadow-sm" />
        <div className="h-24 animate-pulse rounded-2xl bg-white shadow-sm" />
        <div className="h-48 animate-pulse rounded-2xl bg-white shadow-sm" />
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
  const countByStatus = Object.fromEntries(
    STATUSES.map((status) => [status, conversations.filter((c) => c.status === status).length]),
  ) as Record<ConversationStatus, number>;

  const handoffs = conversations.filter((c) => c.handoff_requested_at !== null);
  const pending = conversations.filter((c) => c.status === "PENDING_ADVISOR");
  const avgWaitMinutes =
    pending.length === 0
      ? null
      : Math.round(
          pending.reduce(
            (sum, c) => sum + (now - new Date(c.handoff_requested_at as string).getTime()) / 60_000,
            0,
          ) / pending.length,
        );

  const recent = [...conversations].sort((a, b) => (a.last_message_at < b.last_message_at ? 1 : -1));
  const presentStatuses = STATUSES.filter((s) => countByStatus[s] > 0);

  return (
    <div className="flex flex-col gap-3">
      {/* Señales vitales: un solo instrumento con dos lecturas, no dos cards repetidas. */}
      <div className="flex flex-col divide-y divide-black/5 rounded-2xl bg-white shadow-sm ring-1 ring-inset ring-[color:var(--vmc-color-orange-600)]/20 sm:flex-row sm:divide-x sm:divide-y-0">
        <StatCard
          bare
          size="hero"
          label="Pendientes de asesor"
          value={String(countByStatus.PENDING_ADVISOR)}
          dot={BAR_COLOR.PENDING_ADVISOR}
          valueColor={countByStatus.PENDING_ADVISOR > 0 ? DEEP_COLOR.PENDING_ADVISOR : undefined}
          pulse={countByStatus.PENDING_ADVISOR > 0}
          hint={countByStatus.PENDING_ADVISOR > 0 ? "Nadie los ha tomado todavía" : "La cola está al día"}
          href="/advisor/inbox?estado=pendientes"
        />
        <StatCard
          bare
          size="hero"
          label="Espera promedio"
          value={avgWaitMinutes === null ? "—" : `${avgWaitMinutes} min`}
          dot={BAR_COLOR.PENDING_ADVISOR}
          valueColor={avgWaitMinutes !== null ? DEEP_COLOR.PENDING_ADVISOR : undefined}
          hint="Solo casos pendientes de asesor"
          href="/advisor/inbox?estado=pendientes"
        />
      </div>

      {/* Contexto: volumen general, no exige acción inmediata. */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard label="Conversaciones" value={String(total)} href="/advisor/inbox" />
        <StatCard
          label="En atención"
          value={String(countByStatus.IN_ATTENTION)}
          dot={BAR_COLOR.IN_ATTENTION}
          valueColor={countByStatus.IN_ATTENTION > 0 ? DEEP_COLOR.IN_ATTENTION : undefined}
          href="/advisor/inbox?estado=atencion"
        />
        <StatCard
          label="Cerradas"
          value={String(countByStatus.CLOSED)}
          dot={BAR_COLOR.CLOSED}
          href="/advisor/inbox?estado=cerradas"
        />
        <StatCard label="Casos derivados" value={String(handoffs.length)} hint="Proxy de tickets (D-008)" />
      </div>

      <div className="rounded-2xl bg-white p-3.5 shadow-sm">
        <h2 className="text-xs font-bold uppercase tracking-wide text-neutral-500">Distribución por estado</h2>
        {/* Medidor segmentado, no una barra continua — cada estado es su propio bloque redondeado
            con espacio real entre ellos. Grid + fr reparte el ancho ya restando los gaps. */}
        {total === 0 ? (
          <p className="mt-2.5 text-sm text-neutral-500">Sin conversaciones todavía.</p>
        ) : (
          <>
            <div
              className="mt-2.5 grid h-2.5 gap-1"
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
            <div className="mt-2.5 flex flex-wrap gap-x-4 gap-y-1.5 text-sm">
              {STATUSES.map((status) => (
                <Link
                  key={status}
                  href={`/advisor/inbox?estado=${FILTER_PARAM[status]}`}
                  className="flex items-center gap-1.5 rounded-full text-neutral-600 transition hover:text-[#191C1C]"
                >
                  <span className="h-2 w-2 rounded-full" style={{ background: BAR_COLOR[status] }} />
                  {STATUS_LABEL[status]}
                  <span className="font-bold" style={{ color: DEEP_COLOR[status] }}>
                    {countByStatus[status]}
                  </span>
                </Link>
              ))}
            </div>
          </>
        )}
      </div>

      <div>
        <h2 className="mb-2.5 text-xs font-bold uppercase tracking-wide text-neutral-500">
          Conversaciones recientes
        </h2>
        {recent.length === 0 ? (
          <p className="rounded-2xl bg-white p-6 text-center text-sm text-neutral-500 shadow-sm">
            Sin conversaciones todavía.
          </p>
        ) : (
          <Table
            caption="Conversaciones recientes"
            columns={[
              { header: "Usuario" },
              { header: "Último mensaje", className: "hidden md:table-cell" },
              { header: "Estado", align: "center" },
              { header: "Espera", align: "center" },
              { header: "", align: "right", width: 40 },
            ]}
            rows={recent.map((conv) => [
              <div key="user" className="flex items-center gap-3">
                <span
                  className="h-2 w-2 flex-shrink-0 rounded-full"
                  style={{ background: BAR_COLOR[conv.status] }}
                  aria-hidden
                />
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
              <span key="wait">{formatWaitTime(conv.last_message_at, now)}</span>,
              <div key="open" className="flex justify-end">
                <Link
                  href={`/advisor/inbox/${conv.conversation_id}`}
                  aria-label={`Abrir conversación con ${conv.user_name ?? "usuario anónimo"}`}
                  className="flex h-8 w-8 items-center justify-center rounded-full text-neutral-400 transition hover:bg-[color:var(--vmc-color-vault-500)]/10 hover:text-[color:var(--vmc-color-vault-700)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--vmc-color-vault-500)]"
                >
                  <ChevronRightIcon />
                </Link>
              </div>,
            ])}
          />
        )}
      </div>
    </div>
  );
}
