export default function StatCard({
  label,
  value,
  hint,
  dot,
}: {
  label: string;
  value: string;
  hint?: string;
  /** Color del punto junto al label — liga la tarjeta al mismo color de la barra/leyenda de estado. */
  dot?: string;
}) {
  return (
    <div className="rounded-2xl bg-white p-5 shadow-sm">
      <p className="flex items-center gap-1.5 text-xs font-bold uppercase tracking-wide text-neutral-500">
        {dot && <span className="h-2 w-2 rounded-full" style={{ background: dot }} />}
        {label}
      </p>
      <p className="mt-1 text-3xl font-bold text-[#191C1C]">{value}</p>
      {hint && <p className="mt-1 text-xs text-neutral-500">{hint}</p>}
    </div>
  );
}
