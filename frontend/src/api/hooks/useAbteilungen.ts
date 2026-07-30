import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../client";
import type { Abteilung } from "../types";

export function useAbteilungen() {
  return useQuery({
    queryKey: ["admin", "abteilungen"],
    queryFn: () => apiGet<Abteilung[]>("admin/abteilungen"),
  });
}
