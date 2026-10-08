import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../client";
import type { KlassendienstTyp } from "../types";

export function useKlassendienstTypen() {
  return useQuery({
    queryKey: ["admin", "klassendienst-typen"],
    queryFn: () => apiGet<KlassendienstTyp[]>("admin/klassendienst-typen"),
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });
}
