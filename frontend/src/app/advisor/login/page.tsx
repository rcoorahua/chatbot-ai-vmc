import Link from "next/link";
import Button from "@/concorde/components/Button";

/**
 * Mock de login — RF-006: cuentas de asesor por invitación + Cognito. No hay Cognito real
 * conectado aún; el botón simula el redirect al Hosted UI y navega directo a la bandeja.
 *
 * "Control Tower" (DESIGN.md): fondo violeta sólido (vault-900, no un morado inventado) con una
 * textura de grilla de puntos muy sutil — el panel de instrumentos apagado antes de que el
 * asesor entre a su turno. Sin gradiente en el fondo (esa firma es exclusiva de los controles).
 */
export default function AdvisorLoginPage() {
  return (
    <div
      className="relative flex flex-1 items-center justify-center overflow-hidden px-4"
      style={{ background: "var(--vmc-color-vault-900)" }}
    >
      <div
        className="pointer-events-none absolute inset-0 opacity-[0.06]"
        style={{
          backgroundImage: "radial-gradient(circle, #ffffff 1px, transparent 1px)",
          backgroundSize: "24px 24px",
        }}
        aria-hidden
      />

      <div className="relative w-full max-w-sm rounded-3xl bg-white p-8 text-center shadow-2xl">
        <div
          className="mx-auto mb-5 h-1 w-10 rounded-full"
          style={{ background: "var(--vmc-color-orange-600)" }}
          aria-hidden
        />
        <h1 className="text-3xl font-bold text-[color:var(--vmc-color-vault-700)]">Subastín</h1>
        <p className="mt-1 text-xs font-bold uppercase tracking-wide text-neutral-400">
          Panel de asesor
        </p>
        <p className="mt-4 text-sm text-neutral-500">
          Acceso solo por invitación. Inicia sesión con la cuenta que te asignó tu supervisor.
        </p>
        <Link href="/advisor/inbox" className="mt-7 flex justify-center">
          <Button variant="primary">Continuar con Cognito</Button>
        </Link>
        <p className="mt-5 text-xs text-neutral-400">
          Rol único en el MVP: <code className="text-neutral-500">ADVISOR</code> (RF-007)
        </p>
      </div>
    </div>
  );
}
