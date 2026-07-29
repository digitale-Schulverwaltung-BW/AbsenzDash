import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import * as client from "../client";
import { useRevokeExemption } from "./useRevokeExemption";

describe("useRevokeExemption", () => {
  it("deletes students/:id/exemptions/:exemptionId and invalidates the student detail query", async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");
    const deleteSpy = vi.spyOn(client, "apiDelete").mockResolvedValue(undefined);

    function wrapper({ children }: { children: ReactNode }) {
      return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
    }

    const { result } = renderHook(() => useRevokeExemption(7), { wrapper });
    result.current.mutate(3);

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(deleteSpy).toHaveBeenCalledWith("students/7/exemptions/3");
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["student-detail", 7] });
  });
});
