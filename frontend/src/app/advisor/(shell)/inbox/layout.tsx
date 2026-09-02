"use client";

import { Suspense, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import QueueRow from "@/components/QueueRow";
import { apiErrorMessage, getConversations } from "@/lib/api";
import { useAdvisor } from "@/lib/advisor-context";
import type { Conversation, ConversationStatus } from "@/lib/types";

const FILTERS: Array<{ label: string; statuses: ConversationStatus[] | null; param: string | null }> = [
  { label: "Todas", statuses: null, param: null },
  { label: "Pendientes", statuses: ["PENDING_ADVISOR"], param: "pendientes" },
  { label: "En atención", statuses: ["IN_ATTENTION"], param: "atencion" },
  { label: "Cerradas", statuses: ["CLOSED"], param: "cerradas" },
];

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
    <div className="flex min-h-0 flex-1 gap-4 lg:h-[calc(100dvh-113px)] lg:overflow-hidden">
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
  const filterIndex = Math.max(
    0,
    FILTERS.findIndex((f) => f.param === estado),
  );

  // `result` solo se escribe desde dentro de los callbacks de la promesa (nunca síncrono en el
  // cuerpo del efecto — react-hooks/set-state-in-effect). loading/conversations/error se DERIVAN
  // comparando `result.key` contra el filtro vigente, en vez de guardarse aparte.
  const [result, setResult] = useState<
    { key: number; conversations: Conversation[] } | { key: number; error: string } | null
  >(null);
  const [now] = useState(() => Date.now());

  useEffect(() => {
    let cancelled = false;
    getConversations({ status: FILTERS[filterIndex].statuses?.[0], limit: 100 })
      .then((found) => {
        if (cancelled) return;
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
        setResult({ key: filterIndex, conversations: sorted });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setResult({ key: filterIndex, error: apiErrorMessage(err) });
      });
    return () => {
      cancelled = true;
    };
  }, [filterIndex]);

  const loading = result?.key !== filterIndex;
  const conversations = !loading && result && "conversations" in result ? result.conversations : [];
  const error = !loading && result && "error" in result ? result.error : null;

  function selectFilter(index: number): void {
    const params = new URLSearchParams(searchParams.toString());
    const filter = FILTERS[index];
    if (filter.param) params.set("estado", filter.param);
    else params.delete("estado");
    const query = params.toString();
    router.replace(`${pathname}${query ? `?${query}` : ""}`, { scroll: false });
  }

  const topUrgentId =
    conversations.find((c) => c.status === "PENDING_ADVISOR" && !c.assigned_advisor_id)?.conversation_id ?? null;

  return (
    // Único lugar del panel con scroll interno independiente (cola vs. hilo): el resto de las
    // pantallas usa scroll de página normal. lg:h-[...] resta el header sticky (65px) + el
    // padding vertical de <main> (24px arriba y abajo) para no generar una segunda barra.
    <div className="flex min-h-0 flex-1 gap-4 lg:h-[calc(100dvh-113px)] lg:overflow-hidden">

      <aside
        className={`min-h-0 w-full flex-shrink-0 flex-col gap-3 rounded-2xl bg-white p-3 shadow-sm lg:flex lg:w-96 ${
          activeId ? "hidden" : "flex"
        }`}
      >
        <div className="flex items-center justify-between px-2 pt-1">
          <h2 className="text-xs font-bold uppercase tracking-wide text-neutral-500">Cola de casos</h2>
          <span className="text-xs font-semibold text-neutral-400">{conversations.length}</span>
        </div>
        {/* TabSelector de Concorde impone 83px mínimos por pestaña — 4 no entran en un rail
            angosto sin cortar "Cerradas" sin aviso. Grid de 4 columnas iguales en vez de flex:
            así SIEMPRE es una sola fila, sin envolver ni pedir scroll — el texto se trunca con
            "…" en el peor caso extremo en vez de desaparecer sin aviso. */}
        <div className="grid grid-cols-4 gap-1 px-1" role="tablist" aria-label="Filtrar cola por estado">
          {FILTERS.map((filter, i) => {
            const active = i === filterIndex;
            return (
              <button
                key={filter.label}
                type="button"
                role="tab"
                aria-selected={active}
                onClick={() => selectFilter(i)}
                title={filter.label}
                className={`truncate rounded-full px-1.5 py-1.5 text-center text-[11px] font-semibold transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--vmc-color-vault-500)] ${
                  active
                    ? "bg-gradient-to-br from-[color:var(--vmc-color-vault-500)] to-[color:var(--vmc-color-vault-700)] text-white shadow-sm"
                    : "text-[color:var(--vmc-color-vault-700)] hover:bg-[color:var(--vmc-color-vault-500)]/10"
                }`}
              >
                {filter.label}
              </button>
            );
          })}
        </div>
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
              Nada en &quot;{FILTERS[filterIndex].label}&quot; ahora mismo.
            </p>
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
