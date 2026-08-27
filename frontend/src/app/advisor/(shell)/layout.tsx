"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import Button, { UserIcon } from "@/concorde/components/Button";
import { InboxIcon, ChartIcon } from "@/components/icons";
import { CURRENT_ADVISOR } from "@/lib/mock-data";

const NAV_ITEMS = [
  { href: "/advisor/inbox", label: "Bandeja", icon: InboxIcon },
  { href: "/advisor/dashboard", label: "Dashboard", icon: ChartIcon },
];

/**
 * Shell de la app de asesor (RF-006/RF-029/RF-047): nav simple propia, no el bloque
 * "sidebar" de Concorde (pensado para categorías de subasta, no para una herramienta interna).
 * Los botones/avatares sí vienen de Concorde para mantener el lenguaje visual de marca.
 */
export default function AdvisorShellLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname();

  return (
    <div className="flex min-h-screen overflow-x-hidden bg-[#f7f7fb]">
      <aside className="flex w-16 flex-shrink-0 flex-col gap-1 bg-[#2E0F70] px-2 py-6 md:w-56 md:px-3">
        <p className="mb-6 hidden px-3 text-lg font-bold text-white md:block">Subastín</p>
        {NAV_ITEMS.map((item) => {
          const active = pathname.startsWith(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={active ? "page" : undefined}
              aria-label={item.label}
              className={`flex items-center justify-center gap-2.5 rounded-2xl px-2 py-3 text-sm font-semibold transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white md:justify-start md:px-4 ${
                active ? "bg-white/12 text-white" : "text-[#D1D5DC] hover:bg-white/10 hover:text-white"
              }`}
            >
              <item.icon width={18} height={18} />
              <span className="hidden md:inline">{item.label}</span>
            </Link>
          );
        })}
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-end border-b border-black/5 bg-white px-6 py-3">
          <Button variant="sm-logged-in" icon={<UserIcon />} username={CURRENT_ADVISOR.display_name} />
        </header>
        <main className="min-w-0 flex-1 overflow-y-auto p-6">{children}</main>
      </div>
    </div>
  );
}
