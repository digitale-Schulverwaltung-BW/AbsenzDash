import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../client";
import type { StudentList } from "../types";

export const STUDENT_LIST_LIMIT = 50;

export interface StudentListParams {
  bereichId: number | null;
  klasseId: number | null;
  minStufe: number | null;
  nurAuffaellige: boolean;
  offset: number;
  schuljahrId: number | null;
}

function buildQuery(params: StudentListParams): string {
  const query = new URLSearchParams();
  if (params.bereichId !== null) query.set("bereich_id", String(params.bereichId));
  if (params.klasseId !== null) query.set("klasse_id", String(params.klasseId));
  if (params.minStufe !== null) query.set("min_stufe", String(params.minStufe));
  if (params.nurAuffaellige) query.set("nur_auffaellige", "true");
  if (params.schuljahrId !== null) query.set("schuljahr_id", String(params.schuljahrId));
  query.set("offset", String(params.offset));
  return query.toString();
}

export function useStudents(params: StudentListParams) {
  return useQuery({
    queryKey: ["students", params],
    queryFn: () => apiGet<StudentList>(`students?${buildQuery(params)}`),
  });
}
