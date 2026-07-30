import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import * as client from "../client";
import { useSyncSettings } from "./useSyncSettings";

describe("useSyncSettings", () => {
  it("fetches admin/sync-settings", async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    vi.spyOn(client, "apiGet").mockResolvedValue({
      sync_interval_cron: "*/30 * * * *",
      schuljahr_start_cache: "2025-09-15",
      letzter_sync_am: "2026-07-29T06:00:00Z",
    });

    function wrapper({ children }: { children: ReactNode }) {
      return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
    }

    const { result } = renderHook(() => useSyncSettings(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.sync_interval_cron).toBe("*/30 * * * *");
  });
});
