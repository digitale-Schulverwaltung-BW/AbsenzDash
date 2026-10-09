import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import * as client from "../client";
import { ApiError } from "../client";
import { useTriggerSyncNow } from "./useTriggerSyncNow";

function setup() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const invalidate = vi.spyOn(queryClient, "invalidateQueries");
  function wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  }
  return { wrapper, invalidate };
}

describe("useTriggerSyncNow", () => {
  it("posts to admin/sync-now and invalidates the sync status", async () => {
    const { wrapper, invalidate } = setup();
    const post = vi.spyOn(client, "apiPost").mockResolvedValue({ status: "gestartet", lauf_id: 7 });
    const { result } = renderHook(() => useTriggerSyncNow(), { wrapper });
    act(() => result.current.mutate());
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(post).toHaveBeenCalledWith("admin/sync-now", {});
    expect(result.current.data).toEqual({ status: "gestartet", lauf_id: 7 });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["admin", "sync-status"] });
  });

  it("also refreshes the status after a 409 (a sync is already running)", async () => {
    const { wrapper, invalidate } = setup();
    vi.spyOn(client, "apiPost").mockRejectedValue(new ApiError(409, "conflict"));
    const { result } = renderHook(() => useTriggerSyncNow(), { wrapper });
    act(() => result.current.mutate());
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["admin", "sync-status"] });
  });
});
