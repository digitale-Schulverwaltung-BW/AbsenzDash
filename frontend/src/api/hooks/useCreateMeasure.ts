import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiPost } from "../client";
import type { Massnahme } from "../types";
import { studentDetailQueryKey } from "./useStudentDetail";

export interface CreateMeasureInput {
  massnahmen_typ_id: number;
  datum: string;
  notiz: string | null;
}

export function useCreateMeasure(studentId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: CreateMeasureInput) => apiPost<Massnahme>(`students/${studentId}/measures`, input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: studentDetailQueryKey(studentId) });
    },
  });
}
