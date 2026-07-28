import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../client";
import type { NavOptions } from "../types";

export function useNavOptions() {
  return useQuery({
    queryKey: ["nav-options"],
    queryFn: () => apiGet<NavOptions>("dashboard/nav-options"),
    staleTime: 5 * 60 * 1000,
  });
}
