import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../client";
import type { NavOptions } from "../types";

export function useNavOptions(schuljahrId: number | null = null) {
  const query = schuljahrId !== null ? `?schuljahr_id=${schuljahrId}` : "";
  return useQuery({
    queryKey: ["nav-options", schuljahrId],
    queryFn: () => apiGet<NavOptions>(`dashboard/nav-options${query}`),
    staleTime: 5 * 60 * 1000,
  });
}
