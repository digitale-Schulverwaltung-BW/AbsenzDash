import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../client";
import type { WebuntisDienstOptionen } from "../types";

export function useWebuntisDienstOptionen() {
  return useQuery({
    queryKey: ["admin", "klassendienst-typen", "webuntis-optionen"],
    queryFn: () => apiGet<WebuntisDienstOptionen>("admin/klassendienst-typen/webuntis-optionen"),
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    retry: false,
  });
}
