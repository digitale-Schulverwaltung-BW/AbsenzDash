import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiPost } from "../client";

interface SyncNowResult {
  status: string;
  abgeschlossen_am: string;
}

export function useTriggerSyncNow() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiPost<SyncNowResult>("admin/sync-now", {}),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin", "sync-settings"] }),
  });
}
