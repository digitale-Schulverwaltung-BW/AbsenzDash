import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import * as client from "../client";
import { useExcuseStatuses } from "./useExcuseStatuses";

describe("useExcuseStatuses", () => {
  it("fetches admin/excuse-statuses", async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    vi.spyOn(client, "apiGet").mockResolvedValue([
      { id: 1, name: "entsch.", long_name: "entschuldigt", zaehlt_als_entschuldigt: true, aktiv: true },
    ]);

    function wrapper({ children }: { children: ReactNode }) {
      return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
    }

    const { result } = renderHook(() => useExcuseStatuses(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.[0].name).toBe("entsch.");
  });
});
