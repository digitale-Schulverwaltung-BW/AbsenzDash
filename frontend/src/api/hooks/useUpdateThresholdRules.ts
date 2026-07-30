import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiPut } from "../client";
import type { ThresholdRule } from "../types";

export function useUpdateThresholdRules() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (rules: ThresholdRule[]) => apiPut<ThresholdRule[]>("admin/threshold-rules", rules),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin", "threshold-rules"] }),
  });
}
