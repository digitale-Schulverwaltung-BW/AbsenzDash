import { describe, expect, it } from "vitest";
import { formatDatumDe, heuteIso } from "./datum";

describe("datum", () => {
  it("formats ISO dates in German notation", () => {
    expect(formatDatumDe("2026-09-28")).toBe("28.09.2026");
  });

  it("returns unknown formats unchanged", () => {
    expect(formatDatumDe("morgen")).toBe("morgen");
  });

  it("builds today's local ISO date", () => {
    expect(heuteIso(new Date(2026, 0, 5))).toBe("2026-01-05");
  });
});
