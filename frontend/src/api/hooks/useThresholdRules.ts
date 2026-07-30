import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../client";
import type { ThresholdRule } from "../types";

export function useThresholdRules() {
  return useQuery({
    queryKey: ["admin", "threshold-rules"],
    queryFn: () => apiGet<ThresholdRule[]>("admin/threshold-rules"),
  });
}
