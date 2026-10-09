import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiPut } from "../client";
import type { KlassendienstTyp } from "../types";

export function useUpdateKlassendienstTypen() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (typen: KlassendienstTyp[]) => apiPut<KlassendienstTyp[]>("admin/klassendienst-typen", typen),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "klassendienst-typen"] });
      // Badges/Detail hängen an den Typen (Kürzel, Aktiv, Löschen).
      queryClient.invalidateQueries({ queryKey: ["students"] });
      queryClient.invalidateQueries({ queryKey: ["student-detail"] });
    },
  });
}
