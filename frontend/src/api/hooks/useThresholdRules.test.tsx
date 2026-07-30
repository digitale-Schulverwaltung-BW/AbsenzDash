import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import * as client from "../client";
import { useThresholdRules } from "./useThresholdRules";

describe("useThresholdRules", () => {
  it("fetches admin/threshold-rules", async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    vi.spyOn(client, "apiGet").mockResolvedValue([
      {
        id: 1, typ: "fehlzeiten", geltungsbereich: "schulweit", abteilung_id: null,
        stufen: [{ id: 1, stufe_nr: 1, einheit: "fehltage", schwellenwert: 4, fehlzeiten_filter: "nur_unentschuldigt", empfaenger_rollen: ["klassenlehrkraft"] }],
      },
    ]);

    function wrapper({ children }: { children: ReactNode }) {
      return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
    }

    const { result } = renderHook(() => useThresholdRules(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.[0].stufen[0].schwellenwert).toBe(4);
  });
});
