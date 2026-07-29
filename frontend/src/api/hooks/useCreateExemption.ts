import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiPost } from "../client";
import type { Ausnahme } from "../types";
import { studentDetailQueryKey } from "./useStudentDetail";

export interface CreateExemptionInput {
  kategorie: "fehlzeiten" | "klassenbuch";
  grund: string;
  gueltig_bis: string | null;
}

export function useCreateExemption(studentId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: CreateExemptionInput) => apiPost<Ausnahme>(`students/${studentId}/exemptions`, input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: studentDetailQueryKey(studentId) });
    },
  });
}
