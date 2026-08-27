import Link from "next/link";
import Button from "@/concorde/components/Button";

/**
 * El widget público (RF-001) vive en widget/subastin.js, fuera de este proyecto (PLAN.md).
 * Esta app es solo el panel interno: app de asesor (F5) y dashboard (F7).
 */
export default function Home() {
  return (
    <div className="flex flex-1 items-center justify-center bg-[#2E0F70] px-4">
      <div className="text-center">
        <p className="text-sm font-semibold uppercase tracking-wide text-white/60">Subastín</p>
        <h1 className="mt-1 text-2xl font-bold text-white">Panel interno</h1>
        <Link href="/advisor/login" className="mt-6 flex justify-center">
          <Button variant="primary">Entrar</Button>
        </Link>
      </div>
    </div>
  );
}
