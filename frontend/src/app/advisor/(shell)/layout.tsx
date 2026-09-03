"use client";

import type { ReactNode } from "react";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import Button, { UserIcon } from "@/concorde/components/Button";
import { clearAdvisorToken } from "@/lib/api";
import { AdvisorProvider, useAdvisor } from "@/lib/advisor-context";

const NAV_ITEMS = [
  { href: "/advisor/inbox", label: "Bandeja" },
  { href: "/advisor/dashboard", label: "Dashboard" },
  // Sin "Negocio": esa vista (costo IA, RAG, intents) es para Silvana/Julio, no para quien
  // atiende la bandeja — no existe todavía, se crea cuando D-013 defina acceso (ver
  // ANALISIS-METRICAS-DASHBOARD.md).
];

/**
 * Shell de la app de asesor (RF-006/RF-029/RF-047): header con nav propia (tabs), no barra
 * lateral — con solo 2 destinos una sidebar fija desperdicia ancho y complica el responsive
 * (RF-047 pidió cambiarlo). Botones/avatares vienen de Concorde para marca consistente.
 */
export default function AdvisorShellLayout({ children }: { children: ReactNode }) {
  return (
    <AdvisorProvider>
      <ShellChrome>{children}</ShellChrome>
    </AdvisorProvider>
  );
}

function ShellChrome({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { advisor, error } = useAdvisor();
  const router = useRouter();
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!menuOpen) return;
    function onPointerDown(e: PointerEvent): void {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false);
    }
    function onKeyDown(e: KeyboardEvent): void {
      if (e.key === "Escape") setMenuOpen(false);
    }
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [menuOpen]);

  function logout(): void {
    setMenuOpen(false);
    // ponytail: sin login real (Cognito Hosted UI) todavía — solo borra el token pegado a mano
    // (scripts.advisor_token) y vuelve al mock de /advisor/login. Reemplazar con el logout real
    // de Cognito cuando RF-006 conecte el frontend.
    clearAdvisorToken();
    router.push("/advisor/login");
  }

  return (
    // h-dvh + overflow-hidden en la raíz: el alto total queda fijo a la ventana, nunca aparece
    // la barra de scroll del navegador. <main> es el único que scrollea (si una pantalla como
    // Dashboard tiene más contenido del que cabe) — Bandeja, que sí cabe siempre, usa `h-full`
    // para llenar exactamente lo que <main> le da, sin calcular pixeles del header a mano.
    <div className="flex h-dvh flex-col overflow-hidden bg-[#f7f7fb]">
      <header className="z-20 flex flex-shrink-0 flex-wrap items-center justify-between gap-x-4 gap-y-3 border-b border-black/5 bg-white px-4 py-3 sm:px-6">
        <div className="flex items-center gap-4 sm:gap-6">
          <p className="text-lg font-bold text-[color:var(--vmc-color-vault-700)]">Subastín</p>
          <nav className="flex items-center gap-1.5">
            {NAV_ITEMS.map((item) => {
              const active = pathname.startsWith(item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  aria-current={active ? "page" : undefined}
                  className={`flex h-8 items-center rounded-full px-3 text-xs font-semibold transition ${
                    active
                      ? "bg-gradient-to-br from-[color:var(--vmc-color-vault-500)] to-[color:var(--vmc-color-vault-700)] text-white shadow-sm"
                      : "bg-neutral-100 text-neutral-600 shadow-[inset_0_1px_2px_rgba(0,0,0,0.07)] hover:bg-neutral-200/70 hover:text-neutral-800"
                  }`}
                >
                  {item.label}
                </Link>
              );
            })}
          </nav>
        </div>
        <div ref={menuRef} className="relative">
          <Button
            variant="sm-logged-in"
            icon={<UserIcon />}
            username={error ? "Sin sesión" : (advisor?.name ?? advisor?.email ?? "…")}
            aria-haspopup="menu"
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen((open) => !open)}
          />
          {menuOpen && (
            <div
              role="menu"
              className="absolute right-0 top-[calc(100%+8px)] w-44 overflow-hidden rounded-2xl bg-white py-1 shadow-lg ring-1 ring-black/5"
            >
              <button
                type="button"
                role="menuitem"
                onClick={logout}
                className="w-full px-4 py-2.5 text-left text-sm font-semibold text-neutral-600 transition hover:bg-neutral-100 hover:text-[#8E0B82]"
              >
                Cerrar sesión
              </button>
            </div>
          )}
        </div>
      </header>
      <main className="flex min-h-0 min-w-0 flex-1 flex-col overflow-y-auto p-4 sm:p-6">{children}</main>
    </div>
  );
}
