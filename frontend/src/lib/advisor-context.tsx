"use client";

import { createContext, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { apiErrorMessage, getMe } from "@/lib/api";
import type { Advisor } from "@/lib/types";

interface AdvisorState {
  advisor: Advisor | null;
  loading: boolean;
  error: string | null;
}

/**
 * Identidad real del asesor (GET /advisor/me), una sola vez para toda la app — el header, la
 * bandeja (isMine) y el dashboard la necesitan por igual; sin esto cada página repetiría el
 * mismo fetch. Provisto en (shell)/layout.tsx, que ya envuelve todas las rutas de asesor.
 */
const AdvisorContext = createContext<AdvisorState>({ advisor: null, loading: true, error: null });

export function AdvisorProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AdvisorState>({ advisor: null, loading: true, error: null });

  useEffect(() => {
    let cancelled = false;
    getMe()
      .then((advisor) => {
        if (!cancelled) setState({ advisor, loading: false, error: null });
      })
      .catch((err: unknown) => {
        if (!cancelled) setState({ advisor: null, loading: false, error: apiErrorMessage(err) });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return <AdvisorContext.Provider value={state}>{children}</AdvisorContext.Provider>;
}

export function useAdvisor(): AdvisorState {
  return useContext(AdvisorContext);
}
