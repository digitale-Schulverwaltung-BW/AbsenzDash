import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import * as client from "../client";
import { studentDetailQueryKey, useStudentDetail } from "./useStudentDetail";

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

describe("useStudentDetail", () => {
  it("fetches students/:id and uses studentDetailQueryKey as its query key", async () => {
    const spy = vi.spyOn(client, "apiGet").mockResolvedValue({ id: 7 });

    const { result } = renderHook(() => useStudentDetail(7, null), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(spy).toHaveBeenCalledWith("students/7");
    expect([...studentDetailQueryKey(7), null]).toEqual(["student-detail", 7, null]);
  });

  it("includes schuljahr_id in the request and query key when set", async () => {
    const getSpy = vi.spyOn(client, "apiGet").mockResolvedValue({} as any);
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    function localWrapper({ children }: { children: ReactNode }) {
      return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
    }

    const { result } = renderHook(() => useStudentDetail(7, 27), { wrapper: localWrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(getSpy).toHaveBeenCalledWith("students/7?schuljahr_id=27");
  });

  it("omits schuljahr_id from the request when null", async () => {
    const getSpy = vi.spyOn(client, "apiGet").mockResolvedValue({} as any);
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    function localWrapper({ children }: { children: ReactNode }) {
      return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
    }

    const { result } = renderHook(() => useStudentDetail(7, null), { wrapper: localWrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(getSpy).toHaveBeenCalledWith("students/7");
  });
});
