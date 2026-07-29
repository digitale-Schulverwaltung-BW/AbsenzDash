import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import * as client from "../client";
import { useStudentCatalog } from "./useStudentCatalog";

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

describe("useStudentCatalog", () => {
  it("fetches students/catalog", async () => {
    const spy = vi.spyOn(client, "apiGet").mockResolvedValue({
      massnahmen_typen: [],
      excuse_statuses: [],
      classreg_categories: [],
    });

    const { result } = renderHook(() => useStudentCatalog(), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(spy).toHaveBeenCalledWith("students/catalog");
  });
});
