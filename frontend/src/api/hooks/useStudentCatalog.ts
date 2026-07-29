import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../client";
import type { StudentCatalog } from "../types";

export function useStudentCatalog() {
  return useQuery({
    queryKey: ["student-catalog"],
    queryFn: () => apiGet<StudentCatalog>("students/catalog"),
    staleTime: 5 * 60 * 1000,
  });
}
