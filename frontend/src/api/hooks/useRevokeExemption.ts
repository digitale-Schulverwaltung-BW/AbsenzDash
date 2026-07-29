import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiDelete } from "../client";
import { studentDetailQueryKey } from "./useStudentDetail";

export function useRevokeExemption(studentId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (exemptionId: number) => apiDelete(`students/${studentId}/exemptions/${exemptionId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: studentDetailQueryKey(studentId) });
    },
  });
}
