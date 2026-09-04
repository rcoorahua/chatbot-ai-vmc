"use client";

import { Suspense, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import QueueRow from "@/components/QueueRow";
import { LayersIcon } from "@/components/icons";
import { apiErrorMessage, getConversations } from "@/lib/api";
import { useAdvisor } from "@/lib/advisor-context";
// MOCK_TICKET_TYPE: D-008 (taxonomía real de tickets) sigue sin cerrar — "agrupar por tipo"
// queda como maqueta (ver el title del botón) hasta que haya un problem_type real que agrupar.
import { MOCK_TICKET_TYPE } from "@/lib/mock-data";
import type { Conversation, ConversationStatus } from "@/lib/types";

/**
 * `GET /advisor/conversations` sin `status` NO es "todas" — es la bandeja
 * (`service.list_inbox`), que sin filtro solo trae PENDING_ADVISOR + IN_ATTENTION. Por eso el
 * efecto de abajo siempre pide los 4 estados por separado y los cuentos/filtros de cada tab
 * (incluidas sus vistas hijas) se derivan en memoria — un solo fetch sostiene toda la cola, sin
 * recargar al cambiar de tab.
 */
const ALL_STATUSES: ConversationStatus[] = ["PENDING_ADVISOR", "IN_ATTENTION", "BOT_ATTENDING", "CLOSED"];

type TopFilter = {
  key: string;
  label: string;
  statuses: ConversationStatus[];
  param: string | null;
  children?: Array<{ key: string; label: string; statuses: ConversationStatus[] }>;
};

/**
 * Dos niveles: arriba quién atiende (Subastín = bot, Asesor = KAM humano), abajo pendiente/en
 * atención — pero solo bajo "Asesor": PENDING_ADVISOR vs IN_ATTENTION son dos estados reales.
 * BOT_ATTENDING es uno solo, así que "Subastín" no lleva sub-tabs (inventar un pendiente/en
 * atención ahí sería maquetar un estado que el backend no tiene, D-008 sigue abierta).
 */
const TOP_FILTERS: TopFilter[] = [
  { key: "subastin", label: "Subastín", statuses: ["BOT_ATTENDING"], param: null },
  {
    key: "asesor",
    label: "Asesor",
    statuses: ["PENDING_ADVISOR", "IN_ATTENTION"],
    param: "asesor",
    children: [
      { key: "pendientes", label: "Pendientes", statuses: ["PENDING_ADVISOR"] },
      { key: "atencion", label: "En atención", statuses: ["IN_ATTENTION"] },
    ],
  },
  { key: "cerradas", label: "Cerradas", statuses: ["CLOSED"], param: "cerradas" },
];

const SIN_CLASIFICAR = "Sin clasificar";

/** Agrupa por tipo de ticket — MOCK, D-008 (taxonomía real) sigue abierta. */
function groupByTicketType(conversations: Conversation[]): Array<[string, Conversation[]]> {
  const groups = new Map<string, Conversation[]>();
  for (const conv of conversations) {
    const type = MOCK_TICKET_TYPE[conv.conversation_id] ?? SIN_CLASIFICAR;
    groups.set(type, [...(groups.get(type) ?? []), conv]);
  }
  return [...groups.entries()].sort(([a, ac], [b, bc]) =>
    a === SIN_CLASIFICAR ? 1 : b === SIN_CLASIFICAR ? -1 : bc.length - ac.length,
  );
}

/**
 * Cockpit de triage (mejora UX pedida sobre RF-029/032): la cola vive como rail
 * persistente en vez de una tabla de página completa — abrir un caso ya no navega
 * fuera de la bandeja, solo cambia qué se ve a la derecha. El filtro vive en la URL
 * (?estado=) para que el dashboard pueda enlazar directo a un recorte (D-013).
 * En mobile el rail ocupa toda la pantalla y cede el paso al hilo (RF-047).
 */
/**
 * useSearchParams() (el filtro ?estado=) obliga a envolver en Suspense — si no, Next.js no
 * puede prerenderizar ni siquiera el cascarón estático de /advisor/inbox y el build falla.
 */
export default function InboxLayout({ children }: { children: ReactNode }) {
  return (
    <Suspense fallback={<InboxLayoutFallback />}>
      <InboxLayoutContent>{children}</InboxLayoutContent>
    </Suspense>
  );
}

function InboxLayoutFallback() {
  return (
    <div className="flex min-h-0 flex-1 gap-4 lg:h-full lg:overflow-hidden">
      <div className="hidden w-96 flex-shrink-0 rounded-2xl bg-white p-3 shadow-sm motion-safe:animate-pulse lg:block" />
      <div className="min-h-0 min-w-0 flex-1 rounded-2xl bg-white shadow-sm motion-safe:animate-pulse" />
    </div>
  );
}

function InboxLayoutContent({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const { advisor } = useAdvisor();

  const activeId = pathname.startsWith("/advisor/inbox/") ? pathname.split("/advisor/inbox/")[1] : undefined;
  const estado = searchParams.get("estado");
  const topIndex = Math.max(
    0,
    TOP_FILTERS.findIndex((f) => f.param === estado),
  );
  const topFilter = TOP_FILTERS[topIndex];
  const sub = searchParams.get("sub");
  // Sin "Todas": el primer hijo (Pendientes) es el default, igual que Subastín es el default
  // entre los tabs de arriba — siempre hay uno resaltado, nunca los dos apagados a la vez.
  const activeChild = topFilter.children?.find((c) => c.key === sub) ?? topFilter.children?.[0] ?? null;
  const agruparPorTipo = searchParams.get("agrupar") === "tipo";

  // Un solo fetch para toda la bandeja (los 4 estados); cambiar de tab solo filtra en memoria —
  // ver el comentario de ALL_STATUSES arriba.
  const [result, setResult] = useState<{ conversations: Conversation[] } | { error: string } | null>(null);
  const [now] = useState(() => Date.now());

  useEffect(() => {
    let cancelled = false;
    Promise.all(ALL_STATUSES.map((status) => getConversations({ status, limit: 100 })))
      .then((byStatus) => {
        if (cancelled) return;
        const found = byStatus.flat();
        // El backend no promete un orden total entre estados abiertos y cerrados — el mismo
        // criterio que ya usaba el mock: abiertos primero (más reciente arriba), cerrados
        // después (más reciente arriba también, no al revés).
        const sorted = [...found].sort((a, b) => {
          const aOpen = a.status !== "CLOSED";
          const bOpen = b.status !== "CLOSED";
          if (aOpen !== bOpen) return aOpen ? -1 : 1;
          return aOpen
            ? a.last_message_at.localeCompare(b.last_message_at)
            : b.last_message_at.localeCompare(a.last_message_at);
        });
        setResult({ conversations: sorted });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setResult({ error: apiErrorMessage(err) });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const loading = result === null;
  const allConversations = result && "conversations" in result ? result.conversations : [];
  const error = result && "error" in result ? result.error : null;

  const activeStatuses = activeChild?.statuses ?? topFilter.statuses;
  const conversations = allConversations.filter((c) => activeStatuses.includes(c.status));
  const countFor = (statuses: ConversationStatus[]) =>
    allConversations.filter((c) => statuses.includes(c.status)).length;

  function selectTop(index: number): void {
    const params = new URLSearchParams(searchParams.toString());
    const filter = TOP_FILTERS[index];
    if (filter.param) params.set("estado", filter.param);
    else params.delete("estado");
    params.delete("sub");
    const query = params.toString();
    router.replace(`${pathname}${query ? `?${query}` : ""}`, { scroll: false });
  }

  function selectSub(key: string | null): void {
    const params = new URLSearchParams(searchParams.toString());
    if (key) params.set("sub", key);
    else params.delete("sub");
    const query = params.toString();
    router.replace(`${pathname}${query ? `?${query}` : ""}`, { scroll: false });
  }

  function setAgrupar(porTipo: boolean): void {
    const params = new URLSearchParams(searchParams.toString());
    if (porTipo) params.set("agrupar", "tipo");
    else params.delete("agrupar");
    const query = params.toString();
    router.replace(`${pathname}${query ? `?${query}` : ""}`, { scroll: false });
  }

  const topUrgentId =
    conversations.find((c) => c.status === "PENDING_ADVISOR" && !c.assigned_advisor_id)?.conversation_id ?? null;

  return (
    // h-full (no un cálculo de píxeles a mano): llena exactamente lo que <main> le da, que ya
    // descuenta el header (shell/layout.tsx). Las 3 cards (cola, hilo, contexto) quedan a la
    // MISMA altura (stretch, el default de flex). De las tres, SOLO la cola tiene scroll interno
    // propio (su lista, ver más abajo); hilo y contexto no scrollean — con las conversaciones
    // mock de hoy el contenido siempre entra.
    <div className="flex min-h-0 flex-1 gap-4 lg:h-full lg:overflow-hidden">

      <aside
        className={`min-h-0 w-full flex-shrink-0 flex-col gap-3 rounded-2xl bg-white p-3 shadow-sm lg:flex lg:w-96 ${
          activeId ? "hidden" : "flex"
        }`}
      >
        <div className="flex items-center justify-between px-2 pt-1">
          <h2 className="text-xs font-bold uppercase tracking-wide text-neutral-500">Cola de casos</h2>
          <div className="flex items-center gap-2">
            {/* Agrupar por tipo — maqueta, D-008 sin definir aún. Ícono solo: es una acción
                secundaria de bajo uso, no debe competir en peso visual con los chips de estado. */}
            <button
              type="button"
              onClick={() => setAgrupar(!agruparPorTipo)}
              aria-pressed={agruparPorTipo}
              title="Agrupar por tipo de ticket (maqueta — D-008 sin definir aún)"
              className={`rounded-full p-1 transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--vmc-color-vault-500)] ${
                agruparPorTipo
                  ? "bg-[color:var(--vmc-color-vault-500)]/10 text-[color:var(--vmc-color-vault-700)]"
                  : "text-neutral-400 hover:bg-neutral-100 hover:text-neutral-600"
              }`}
            >
              <LayersIcon width={15} height={15} />
            </button>
            <span className="text-xs font-semibold text-neutral-400">{conversations.length}</span>
          </div>
        </div>
        {/* TabSelector de Concorde impone 83px mínimos por pestaña — 4 no entraban en un rail
            angosto sin cortar texto sin aviso; con 3 (sin "Todas", quitado por ser puro ruido
            visual sobre Subastín+Asesor+Cerradas) el grid ya no está al límite. Grid de columnas
            iguales en vez de flex: así SIEMPRE es una sola fila, sin envolver ni pedir scroll. */}
        <div className="grid grid-cols-3 gap-1 px-1" role="tablist" aria-label="Filtrar cola por quién atiende">
          {TOP_FILTERS.map((filter, i) => {
            const active = i === topIndex;
            return (
              <button
                key={filter.key}
                type="button"
                role="tab"
                aria-selected={active}
                onClick={() => selectTop(i)}
                title={filter.label}
                className={`truncate rounded-full px-1.5 py-1.5 text-center text-[11px] font-semibold transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--vmc-color-vault-500)] ${
                  active
                    ? "bg-gradient-to-br from-[color:var(--vmc-color-vault-500)] to-[color:var(--vmc-color-vault-700)] text-white shadow-sm"
                    : "bg-neutral-100 text-[color:var(--vmc-color-vault-700)] shadow-[inset_0_1px_2px_rgba(0,0,0,0.07)] hover:bg-neutral-200/70"
                }`}
              >
                {filter.label} {!loading && `(${countFor(filter.statuses)})`}
              </button>
            );
          })}
        </div>
        {/* Sub-tabs: solo "Asesor" los tiene — PENDING_ADVISOR y IN_ATTENTION son dos estados
            reales del backend; "Subastín" es un único estado (BOT_ATTENDING), inventarle un
            pendiente/en atención sería maquetar algo que D-008 no define. */}
        {topFilter.children && (
          <div className="flex gap-1 px-1" role="tablist" aria-label="Filtrar Asesor por estado">
            {topFilter.children.map((child) => (
              <button
                key={child.key}
                type="button"
                role="tab"
                aria-selected={activeChild?.key === child.key}
                onClick={() => selectSub(child.key)}
                className={`rounded-full px-2 py-1 text-[11px] font-medium transition ${
                  activeChild?.key === child.key
                    ? "bg-[color:var(--vmc-color-vault-500)]/15 text-[color:var(--vmc-color-vault-700)]"
                    : "text-neutral-500 hover:bg-neutral-100"
                }`}
              >
                {child.label} {!loading && `(${countFor(child.statuses)})`}
              </button>
            ))}
          </div>
        )}
        <div className="flex min-h-0 flex-1 flex-col divide-y divide-black/5 overflow-y-auto">
          {loading ? (
            <div className="flex flex-col gap-2 p-2">
              {[0, 1, 2].map((i) => (
                <div key={i} className="h-14 animate-pulse rounded-xl bg-neutral-100" />
              ))}
            </div>
          ) : error ? (
            <p className="px-3 py-8 text-center text-sm text-[#9A4A0F]">{error}</p>
          ) : conversations.length === 0 ? (
            <p className="px-3 py-8 text-center text-sm text-neutral-500">
              Nada en &quot;{activeChild?.label ?? topFilter.label}&quot; ahora mismo.
            </p>
          ) : agruparPorTipo ? (
            groupByTicketType(conversations).map(([type, convs]) => (
              <div key={type} className="pb-2">
                <p className="px-3 pb-1 pt-2 text-[11px] font-bold uppercase tracking-wide text-neutral-400">
                  {type} · {convs.length}
                </p>
                <div className="flex flex-col divide-y divide-black/5">
                  {convs.map((conv) => (
                    <QueueRow
                      key={conv.conversation_id}
                      conversation={conv}
                      active={conv.conversation_id === activeId}
                      mostUrgent={conv.conversation_id === topUrgentId}
                      now={now}
                      isMine={conv.assigned_advisor_id === advisor?.advisor_id}
                    />
                  ))}
                </div>
              </div>
            ))
          ) : (
            conversations.map((conv) => (
              <QueueRow
                key={conv.conversation_id}
                conversation={conv}
                active={conv.conversation_id === activeId}
                mostUrgent={conv.conversation_id === topUrgentId}
                now={now}
                isMine={conv.assigned_advisor_id === advisor?.advisor_id}
              />
            ))
          )}
        </div>
      </aside>

      <section className={`min-h-0 min-w-0 flex-1 flex-col lg:flex ${activeId ? "flex" : "hidden lg:flex"}`}>
        {children}
      </section>
    </div>
  );
}
