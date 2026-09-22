import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import * as client from "../client";
import { useNavOptions } from "./useNavOptions";

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

describe("useNavOptions", () => {
  it("omits schuljahr_id when unset", async () => {
    const spy = vi.spyOn(client, "apiGet").mockResolvedValue({});

    const { result } = renderHook(() => useNavOptions(), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(spy).toHaveBeenCalledWith("dashboard/nav-options");
  });

  it("includes schuljahr_id in the query string when set", async () => {
    const spy = vi.spyOn(client, "apiGet").mockResolvedValue({});

    const { result } = renderHook(() => useNavOptions(27), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(spy).toHaveBeenCalledWith("dashboard/nav-options?schuljahr_id=27");
  });
});
