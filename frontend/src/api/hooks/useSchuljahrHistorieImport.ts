import { useMutation } from "@tanstack/react-query";
import { apiPostFormData } from "../client";
import type { HistorieImportResult } from "../types";

interface ImportArgs {
  schuljahrId: number;
  file: File;
}

export function useSchuljahrHistorieImport() {
  return useMutation({
    mutationFn: ({ schuljahrId, file }: ImportArgs) => {
      const formData = new FormData();
      formData.append("schuljahr_id", String(schuljahrId));
      formData.append("file", file);
      return apiPostFormData<HistorieImportResult>("admin/schuljahr-historie-import", formData);
    },
  });
}
