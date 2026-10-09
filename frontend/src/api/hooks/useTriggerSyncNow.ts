import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiPost } from "../client";

interface SyncNowResult {
  status: "gestartet";
  lauf_id: number;
}

export function useTriggerSyncNow() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiPost<SyncNowResult>("admin/sync-now", {}),
    // Auch nach einem Fehler (z. B. 409: läuft schon) den Status neu laden.
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["admin", "sync-status"] }),
  });
}
