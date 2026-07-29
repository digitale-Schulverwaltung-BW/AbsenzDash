import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../client";
import type { StudentDetail } from "../types";

export function studentDetailQueryKey(studentId: number) {
  return ["student-detail", studentId] as const;
}

export function useStudentDetail(studentId: number) {
  return useQuery({
    queryKey: studentDetailQueryKey(studentId),
    queryFn: () => apiGet<StudentDetail>(`students/${studentId}`),
  });
}
