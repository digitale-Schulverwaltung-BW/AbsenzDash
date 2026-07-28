import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../client";
import type { Stats } from "../types";

export function useStats(bereichId: number | null, klasseId: number | null) {
  const params = new URLSearchParams();
  if (bereichId !== null) params.set("bereich_id", String(bereichId));
  if (klasseId !== null) params.set("klasse_id", String(klasseId));
  const query = params.toString();

  return useQuery({
    queryKey: ["dashboard-stats", bereichId, klasseId],
    queryFn: () => apiGet<Stats>(`dashboard/stats${query ? `?${query}` : ""}`),
  });
}
