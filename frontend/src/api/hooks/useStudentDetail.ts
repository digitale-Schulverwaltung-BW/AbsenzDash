import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../client";
import type { StudentDetail } from "../types";

export function studentDetailQueryKey(studentId: number) {
  return ["student-detail", studentId] as const;
}

export function useStudentDetail(studentId: number, schuljahrId: number | null) {
  return useQuery({
    queryKey: [...studentDetailQueryKey(studentId), schuljahrId] as const,
    queryFn: () =>
      apiGet<StudentDetail>(
        schuljahrId !== null ? `students/${studentId}?schuljahr_id=${schuljahrId}` : `students/${studentId}`,
      ),
  });
}
