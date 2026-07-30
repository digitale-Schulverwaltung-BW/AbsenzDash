import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../client";
import type { ExcuseStatus } from "../types";

export function useExcuseStatuses() {
  return useQuery({
    queryKey: ["admin", "excuse-statuses"],
    queryFn: () => apiGet<ExcuseStatus[]>("admin/excuse-statuses"),
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });
}
