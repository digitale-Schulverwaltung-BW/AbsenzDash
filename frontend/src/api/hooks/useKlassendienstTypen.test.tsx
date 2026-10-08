import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import * as client from "../client";
import { useKlassendienstTypen } from "./useKlassendienstTypen";
import { useUpdateKlassendienstTypen } from "./useUpdateKlassendienstTypen";
import { useWebuntisDienstOptionen } from "./useWebuntisDienstOptionen";

function setup() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  function wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  }
  return { queryClient, wrapper };
}

describe("Klassendienst hooks", () => {
  it("fetches admin/klassendienst-typen", async () => {
    const { wrapper } = setup();
    const spy = vi.spyOn(client, "apiGet").mockResolvedValue([
      { id: 1, webuntis_dienst_id: 26, bezeichnung: "Entschuldigungspflicht", kuerzel: "E", beschreibung: null, aktiv: true },
    ]);
    const { result } = renderHook(() => useKlassendienstTypen(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(spy).toHaveBeenCalledWith("admin/klassendienst-typen");
    expect(result.current.data?.[0].kuerzel).toBe("E");
  });

  it("fetches the webuntis options", async () => {
    const { wrapper } = setup();
    const spy = vi.spyOn(client, "apiGet").mockResolvedValue({ optionen: [{ id: 26, bezeichnung: "X" }], hinweis: null });
    const { result } = renderHook(() => useWebuntisDienstOptionen(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(spy).toHaveBeenCalledWith("admin/klassendienst-typen/webuntis-optionen");
    expect(result.current.data?.optionen).toHaveLength(1);
  });

  it("PUTs the list and invalidates dependent queries", async () => {
    const { queryClient, wrapper } = setup();
    const put = vi.spyOn(client, "apiPut").mockResolvedValue([]);
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");
    const { result } = renderHook(() => useUpdateKlassendienstTypen(), { wrapper });
    await act(async () => {
      result.current.mutate([{ webuntis_dienst_id: 26, bezeichnung: "E", kuerzel: "E", aktiv: true }]);
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(put).toHaveBeenCalledWith("admin/klassendienst-typen", [
      { webuntis_dienst_id: 26, bezeichnung: "E", kuerzel: "E", aktiv: true },
    ]);
    const keys = invalidate.mock.calls.map((call) => (call[0] as { queryKey: unknown[] }).queryKey[0]);
    expect(keys).toEqual(expect.arrayContaining(["admin", "students", "student-detail"]));
  });
});
