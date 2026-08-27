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
 * Shell de la app de asesor (RF-006/RF-029/RF-047): header con nav propia (tabs), no barra
 * lateral — con solo 2 destinos una sidebar fija desperdicia ancho y complica el responsive
 * (RF-047 pidió cambiarlo). Botones/avatares vienen de Concorde para marca consistente.
 */
export default function AdvisorShellLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname();

  return (
    <div className="flex min-h-screen flex-col overflow-x-hidden bg-[#f7f7fb]">
      <header className="flex flex-wrap items-center justify-between gap-x-4 gap-y-3 border-b border-black/5 bg-white px-4 py-3 sm:px-6">
        <div className="flex items-center gap-4 sm:gap-6">
          <p className="text-lg font-bold text-[color:var(--vmc-color-vault-700)]">Subastín</p>
          <nav className="flex items-center gap-1">
            {NAV_ITEMS.map((item) => {
              const active = pathname.startsWith(item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  aria-current={active ? "page" : undefined}
                  aria-label={item.label}
                  className={`flex items-center gap-2 rounded-full px-3 py-2 text-sm font-semibold transition sm:px-4 ${
                    active
                      ? "bg-[color:var(--vmc-color-vault-500)]/10 text-[color:var(--vmc-color-vault-700)]"
                      : "text-neutral-500 hover:text-neutral-700"
                  }`}
                >
                  <item.icon width={16} height={16} />
                  <span className="hidden sm:inline">{item.label}</span>
                </Link>
              );
            })}
          </nav>
        </div>
        <Button variant="sm-logged-in" icon={<UserIcon />} username={CURRENT_ADVISOR.display_name} />
      </header>
      <main className="min-w-0 flex-1 overflow-y-auto p-6">{children}</main>
    </div>
  );
}
