import { describe, expect, it } from "vitest";
import { formatDatumDe, formatUhrzeitDe, heuteIso } from "./datum";

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

  it("formats an ISO timestamp as local hh:mm", () => {
    const d = new Date(2026, 9, 9, 7, 5);
    expect(formatUhrzeitDe(d.toISOString())).toBe("07:05");
  });

  it("returns unparsable timestamps unchanged", () => {
    expect(formatUhrzeitDe("gestern")).toBe("gestern");
  });
});
