import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../client";
import type { SyncSettings } from "../types";

export function useSyncSettings() {
  return useQuery({
    queryKey: ["admin", "sync-settings"],
    queryFn: () => apiGet<SyncSettings>("admin/sync-settings"),
  });
}
