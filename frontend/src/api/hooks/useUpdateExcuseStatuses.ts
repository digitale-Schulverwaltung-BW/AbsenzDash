import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiPut } from "../client";
import type { ExcuseStatus } from "../types";

export function useUpdateExcuseStatuses() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (statuses: ExcuseStatus[]) => apiPut<ExcuseStatus[]>("admin/excuse-statuses", statuses),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin", "excuse-statuses"] }),
  });
}
