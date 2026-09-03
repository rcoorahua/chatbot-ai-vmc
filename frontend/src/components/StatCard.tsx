import Link from "next/link";
import type { CSSProperties } from "react";

export type StatCardSize = "hero" | "compact";

export default function StatCard({
  label,
  value,
  hint,
  dot,
  valueColor,
  pulse = false,
  href,
  size = "compact",
  bare = false,
}: {
  label: string;
  value: string;
  hint?: string;
  /** Color del punto junto al label — liga la tarjeta al mismo color de la barra/leyenda de estado. */
  dot?: string;
  /** Tono oscuro (contraste AA sobre blanco) para el número — solo cuando el valor mismo debe leerse
   * como señal, no solo el punto. Nunca el hex saturado de `dot`: ese falla contraste como texto grande. */
  valueColor?: string;
  /** El punto de estado late — reservar para la única señal que de verdad exige atención ahora. */
  pulse?: boolean;
  /** Cuando existe, la tarjeta enlaza al recorte de la cola que representa (dashboard → cockpit). */
  href?: string;
  /** "hero" = la señal vital que manda en el vistazo; "compact" = contexto secundario. */
  size?: StatCardSize;
  /** Sin card propia (fondo/sombra/radio) — para vivir como celda dentro de un cluster que ya es una sola card. */
  bare?: boolean;
}) {
  const isHero = size === "hero";
  const glowStyle: CSSProperties | undefined = dot
    ? ({ "--stat-glow": `${dot}4D`, "--stat-ring": `${dot}33` } as CSSProperties)
    : undefined;

  const body = (
    <div className={`flex flex-col ${isHero ? "gap-1.5" : "gap-0.5"}`}>
      <p className="flex items-center gap-1.5 text-xs font-bold uppercase tracking-wide text-neutral-500">
        {dot && (
          <span className="relative flex h-1.5 w-1.5">
            {pulse && (
              <span
                className="absolute inline-flex h-full w-full rounded-full opacity-75 motion-safe:animate-ping"
                style={{ background: dot }}
              />
            )}
            <span className="relative inline-flex h-1.5 w-1.5 rounded-full" style={{ background: dot }} />
          </span>
        )}
        {label}
      </p>
      <p
        className={`font-bold ${isHero ? "text-[2.75rem] leading-none tracking-tight" : "text-lg"}`}
        style={{ color: valueColor ?? "#191C1C" }}
      >
        {value}
      </p>
      {hint && <p className="text-xs text-neutral-500">{hint}</p>}
    </div>
  );

  if (bare) {
    const cellClass = `flex-1 transition hover:bg-black/[0.02] ${isHero ? "px-5 py-4" : "px-4 py-3"}`;
    return href ? (
      <Link href={href} className={cellClass}>
        {body}
      </Link>
    ) : (
      <div className={cellClass}>{body}</div>
    );
  }

  const sizeClass = isHero ? "px-4 py-3" : "px-3 py-2.5";
  const ringClass = isHero && dot ? "ring-1 ring-inset ring-[color:var(--stat-ring)]" : "";

  if (href) {
    return (
      <Link
        href={href}
        style={glowStyle}
        className={`block rounded-2xl bg-white shadow-sm transition hover:-translate-y-0.5 hover:shadow-[0_10px_28px_-6px_var(--stat-glow,transparent)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--vmc-color-vault-500)] ${sizeClass} ${ringClass}`}
      >
        {body}
      </Link>
    );
  }

  return (
    <div style={glowStyle} className={`rounded-2xl bg-white shadow-sm ${sizeClass} ${ringClass}`}>
      {body}
    </div>
  );
}
