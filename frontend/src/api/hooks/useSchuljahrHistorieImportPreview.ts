import { useMutation } from "@tanstack/react-query";
import { apiPostFormData } from "../client";
import type { HistorieImportPreview } from "../types";

interface PreviewArgs {
  schuljahrId: number;
  file: File;
}

export function useSchuljahrHistorieImportPreview() {
  return useMutation({
    mutationFn: ({ schuljahrId, file }: PreviewArgs) => {
      const formData = new FormData();
      formData.append("schuljahr_id", String(schuljahrId));
      formData.append("file", file);
      return apiPostFormData<HistorieImportPreview>("admin/schuljahr-historie-import/preview", formData);
    },
  });
}
