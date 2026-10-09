import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { apiGet } from "../client";
import type { SyncStatus } from "../types";

const POLL_INTERVAL_MS = 3000;

/** Sync-Status; pollt nur, solange ein Sync läuft. Nach dem Ende werden die Sync-Einstellungen
 *  (u. a. "Letzter Sync") neu geladen. */
export function useSyncStatus() {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: ["admin", "sync-status"],
    queryFn: () => apiGet<SyncStatus>("admin/sync-status"),
    refetchInterval: (q) => (q.state.data?.laeuft ? POLL_INTERVAL_MS : false),
    refetchOnWindowFocus: false,
  });

  const laeuft = query.data?.laeuft;
  const zuvorLief = useRef(false);
  useEffect(() => {
    if (laeuft === undefined) return;
    if (zuvorLief.current && !laeuft) {
      void queryClient.invalidateQueries({ queryKey: ["admin", "sync-settings"] });
    }
    zuvorLief.current = laeuft;
  }, [laeuft, queryClient]);

  return query;
}
