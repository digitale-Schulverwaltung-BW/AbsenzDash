import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../client";
import type { ThresholdCoverage } from "../types";

// Query-Key beginnt mit dem der Regeln, damit das Speichern (invalidateQueries auf
// ["admin", "threshold-rules"]) die Abdeckung automatisch neu laedt.
export function useThresholdCoverage() {
  return useQuery({
    queryKey: ["admin", "threshold-rules", "coverage"],
    queryFn: () => apiGet<ThresholdCoverage[]>("admin/threshold-rules/coverage"),
  });
}
