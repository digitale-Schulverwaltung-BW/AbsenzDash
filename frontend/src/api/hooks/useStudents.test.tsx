import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import * as client from "../client";
import { useStudents } from "./useStudents";

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

describe("useStudents", () => {
  it("builds the query string from the given filter params", async () => {
    const spy = vi.spyOn(client, "apiGet").mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 });

    const { result } = renderHook(
      () =>
        useStudents({ bereichId: 3, klasseId: null, minStufe: 2, nurAuffaellige: true, offset: 50, schuljahrId: null }),
      { wrapper },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(spy).toHaveBeenCalledWith("students?bereich_id=3&min_stufe=2&nur_auffaellige=true&offset=50");
  });

  it("omits unset filters", async () => {
    const spy = vi.spyOn(client, "apiGet").mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 });

    const { result } = renderHook(
      () =>
        useStudents({
          bereichId: null,
          klasseId: null,
          minStufe: null,
          nurAuffaellige: false,
          offset: 0,
          schuljahrId: null,
        }),
      { wrapper },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(spy).toHaveBeenCalledWith("students?offset=0");
  });

  it("includes schuljahr_id in the query string when set", async () => {
    const spy = vi.spyOn(client, "apiGet").mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 });

    const { result } = renderHook(
      () =>
        useStudents({
          bereichId: null,
          klasseId: null,
          minStufe: null,
          nurAuffaellige: false,
          offset: 0,
          schuljahrId: 27,
        }),
      { wrapper },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(spy).toHaveBeenCalledWith("students?schuljahr_id=27&offset=0");
  });
});
