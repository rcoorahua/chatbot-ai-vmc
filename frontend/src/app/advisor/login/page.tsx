import Link from "next/link";
import Button from "@/concorde/components/Button";

/**
 * Mock de login — RF-006: cuentas de asesor por invitación + Cognito. No hay Cognito real
 * conectado aún; el botón simula el redirect al Hosted UI y navega directo a la bandeja.
 */
export default function AdvisorLoginPage() {
  return (
    <div className="flex flex-1 items-center justify-center bg-[#2E0F70] px-4">
      <div className="w-full max-w-sm rounded-3xl bg-white p-8 text-center shadow-2xl">
        <p className="text-sm font-semibold uppercase tracking-wide text-[color:var(--vmc-color-vault-600)]">
          Subastín
        </p>
        <h1 className="mt-1 text-xl font-bold text-[#191C1C]">Panel de asesor</h1>
        <p className="mt-2 text-sm text-neutral-500">
          Acceso solo por invitación. Inicia sesión con la cuenta que te asignó tu supervisor.
        </p>
        <Link href="/advisor/inbox" className="mt-6 flex justify-center">
          <Button variant="primary">Continuar con Cognito</Button>
        </Link>
        <p className="mt-4 text-xs text-neutral-400">
          Rol único en el MVP: <code>ADVISOR</code> (RF-007).
        </p>
      </div>
    </div>
  );
}
