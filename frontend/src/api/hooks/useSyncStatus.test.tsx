import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as client from "../client";
import type { SyncStatus } from "../types";
import { useSyncStatus } from "./useSyncStatus";

const IDLE: SyncStatus = { laeuft: false, aktueller_lauf: null, letzter_lauf: null };
const RUNNING: SyncStatus = {
  laeuft: true,
  aktueller_lauf: { id: 3, gestartet_am: "2026-10-09T07:00:00Z", phase: "Fehlzeiten", ausgeloest_von: "manuell" },
  letzter_lauf: null,
};

function setup() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidate = vi.spyOn(queryClient, "invalidateQueries");
  function wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  }
  return { wrapper, invalidate };
}

describe("useSyncStatus", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("fetches admin/sync-status once on mount", async () => {
    const get = vi.spyOn(client, "apiGet").mockResolvedValue(IDLE);
    const { result } = renderHook(() => useSyncStatus(), { wrapper: setup().wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(get).toHaveBeenCalledWith("admin/sync-status");
    expect(result.current.data).toEqual(IDLE);
  });

  it("polls every 3 seconds while a sync is running", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const get = vi.spyOn(client, "apiGet").mockResolvedValue(RUNNING);
    const { result } = renderHook(() => useSyncStatus(), { wrapper: setup().wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(get).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(3100);
    await waitFor(() => expect(get.mock.calls.length).toBeGreaterThanOrEqual(2));
    await vi.advanceTimersByTimeAsync(3100);
    await waitFor(() => expect(get.mock.calls.length).toBeGreaterThanOrEqual(3));
  });

  it("does not poll while idle", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const get = vi.spyOn(client, "apiGet").mockResolvedValue(IDLE);
    const { result } = renderHook(() => useSyncStatus(), { wrapper: setup().wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    await vi.advanceTimersByTimeAsync(20000);
    expect(get).toHaveBeenCalledTimes(1);
  });

  it("stops polling once the sync has finished and refreshes the sync settings", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const get = vi
      .spyOn(client, "apiGet")
      .mockResolvedValueOnce(RUNNING)
      .mockResolvedValue({ ...IDLE, letzter_lauf: { id: 3, status: "ok", gestartet_am: "a", beendet_am: "b", ausgeloest_von: "manuell", fehler_kurz: null } });
    const { wrapper, invalidate } = setup();
    const { result } = renderHook(() => useSyncStatus(), { wrapper });
    await waitFor(() => expect(result.current.data?.laeuft).toBe(true));
    await vi.advanceTimersByTimeAsync(3100);
    await waitFor(() => expect(result.current.data?.laeuft).toBe(false));
    await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ["admin", "sync-settings"] }));
    const calls = get.mock.calls.length;
    await vi.advanceTimersByTimeAsync(20000);
    expect(get.mock.calls.length).toBe(calls);
  });
});
