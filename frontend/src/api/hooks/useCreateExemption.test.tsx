import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import * as client from "../client";
import { useCreateExemption } from "./useCreateExemption";

describe("useCreateExemption", () => {
  it("posts to students/:id/exemptions and invalidates the student detail query", async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");
    const postSpy = vi.spyOn(client, "apiPost").mockResolvedValue({ id: 1 });

    function wrapper({ children }: { children: ReactNode }) {
      return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
    }

    const { result } = renderHook(() => useCreateExemption(7), { wrapper });
    result.current.mutate({ kategorie: "fehlzeiten", grund: "Attest", gueltig_bis: null });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(postSpy).toHaveBeenCalledWith("students/7/exemptions", {
      kategorie: "fehlzeiten",
      grund: "Attest",
      gueltig_bis: null,
    });
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["student-detail", 7] });
  });
});
