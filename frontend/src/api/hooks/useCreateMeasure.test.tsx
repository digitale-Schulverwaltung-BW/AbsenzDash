import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import * as client from "../client";
import { useCreateMeasure } from "./useCreateMeasure";

describe("useCreateMeasure", () => {
  it("posts to students/:id/measures and invalidates the student detail query", async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");
    const postSpy = vi.spyOn(client, "apiPost").mockResolvedValue({ id: 1 });

    function wrapper({ children }: { children: ReactNode }) {
      return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
    }

    const { result } = renderHook(() => useCreateMeasure(7), { wrapper });
    result.current.mutate({ massnahmen_typ_id: 2, datum: "2026-07-28", notiz: null });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(postSpy).toHaveBeenCalledWith("students/7/measures", {
      massnahmen_typ_id: 2,
      datum: "2026-07-28",
      notiz: null,
    });
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["student-detail", 7] });
  });
});
