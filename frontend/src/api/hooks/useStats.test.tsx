import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import * as client from "../client";
import { useStats } from "./useStats";

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

describe("useStats", () => {
  it("builds the query string from bereichId/klasseId", async () => {
    const spy = vi.spyOn(client, "apiGet").mockResolvedValue({});

    const { result } = renderHook(() => useStats(3, null, null), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(spy).toHaveBeenCalledWith("dashboard/stats?bereich_id=3");
  });

  it("omits unset filters", async () => {
    const spy = vi.spyOn(client, "apiGet").mockResolvedValue({});

    const { result } = renderHook(() => useStats(null, null, null), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(spy).toHaveBeenCalledWith("dashboard/stats");
  });

  it("includes schuljahr_id in the query string when set", async () => {
    const spy = vi.spyOn(client, "apiGet").mockResolvedValue({});

    const { result } = renderHook(() => useStats(null, null, 27), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(spy).toHaveBeenCalledWith("dashboard/stats?schuljahr_id=27");
  });

  it("combines bereichId, klasseId and schuljahrId", async () => {
    const spy = vi.spyOn(client, "apiGet").mockResolvedValue({});

    const { result } = renderHook(() => useStats(3, 5, 27), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(spy).toHaveBeenCalledWith("dashboard/stats?bereich_id=3&klasse_id=5&schuljahr_id=27");
  });
});
