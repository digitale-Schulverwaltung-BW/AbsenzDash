import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiPut } from "../client";
import type { SyncSettings } from "../types";

export function useUpdateSyncSettings() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (sync_interval_cron: string) => apiPut<SyncSettings>("admin/sync-settings", { sync_interval_cron }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin", "sync-settings"] }),
  });
}
