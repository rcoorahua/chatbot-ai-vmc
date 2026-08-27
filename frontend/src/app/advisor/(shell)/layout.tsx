import type { ReactNode } from "react";
import Link from "next/link";
import Button, { UserIcon } from "@/concorde/components/Button";
import { CURRENT_ADVISOR } from "@/lib/mock-data";

const NAV_ITEMS = [
  { href: "/advisor/inbox", label: "Bandeja" },
  { href: "/advisor/dashboard", label: "Dashboard" },
];

/**
 * Shell de la app de asesor (RF-006/RF-029/RF-047): nav simple propia, no el bloque
 * "sidebar" de Concorde (pensado para categorías de subasta, no para una herramienta interna).
 * Los botones/avatares sí vienen de Concorde para mantener el lenguaje visual de marca.
 */
export default function AdvisorShellLayout({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-screen bg-[#f7f7fb]">
      <aside className="flex w-56 flex-col gap-1 bg-[#2E0F70] px-3 py-6">
        <p className="mb-6 px-3 text-lg font-bold text-white">Subastín</p>
        {NAV_ITEMS.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className="rounded-2xl px-4 py-3 text-sm font-semibold text-[#D1D5DC] transition hover:bg-white/10 hover:text-white"
          >
            {item.label}
          </Link>
        ))}
      </aside>
      <div className="flex flex-1 flex-col">
        <header className="flex items-center justify-end border-b border-black/5 bg-white px-6 py-3">
          <Button variant="sm-logged-in" icon={<UserIcon />} username={CURRENT_ADVISOR.display_name} />
        </header>
        <main className="flex-1 overflow-y-auto p-6">{children}</main>
      </div>
    </div>
  );
}
