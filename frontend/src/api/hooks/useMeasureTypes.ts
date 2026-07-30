import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../client";
import type { MeasureType } from "../types";

export function useMeasureTypes() {
  return useQuery({
    queryKey: ["admin", "measure-types"],
    queryFn: () => apiGet<MeasureType[]>("admin/measure-types"),
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });
}
