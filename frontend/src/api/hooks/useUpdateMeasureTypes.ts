import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiPut } from "../client";
import type { MeasureType } from "../types";

export function useUpdateMeasureTypes() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (types: MeasureType[]) => apiPut<MeasureType[]>("admin/measure-types", types),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin", "measure-types"] }),
  });
}
