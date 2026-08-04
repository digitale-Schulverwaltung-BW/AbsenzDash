import { describe, expect, it } from "vitest";
import { buildKlasseNavigationParams, resolveEntryClickTarget } from "./entryClickTarget";

describe("resolveEntryClickTarget", () => {
  it.each(["schule", "eigene_bereiche"] as const)(
    "resolves to a Bereich target for level %s",
    (level) => {
      expect(resolveEntryClickTarget(level, 5)).toEqual({ typ: "bereich", id: 5 });
    },
  );

  it.each(["bereich", "eigene_klassen"] as const)(
    "resolves to a Klasse target for level %s",
    (level) => {
      expect(resolveEntryClickTarget(level, 7)).toEqual({ typ: "klasse", id: 7 });
    },
  );
});

describe("buildKlasseNavigationParams", () => {
  it("keeps the current bereich when navigating from a Bereich's chart into one of its Klassen", () => {
    const current = new URLSearchParams({ bereich: "3" });

    const result = buildKlasseNavigationParams(current, 7);

    expect(result.get("klasse")).toBe("7");
    expect(result.get("bereich")).toBe("3");
  });

  it("carries the schuljahr over as well", () => {
    const current = new URLSearchParams({ bereich: "3", schuljahr: "2024" });

    const result = buildKlasseNavigationParams(current, 7);

    expect(result.get("schuljahr")).toBe("2024");
  });

  it("omits bereich when there was none (e.g. eigene_klassen level)", () => {
    const current = new URLSearchParams();

    const result = buildKlasseNavigationParams(current, 7);

    expect(result.has("bereich")).toBe(false);
    expect(Array.from(result.keys())).toEqual(["klasse"]);
  });
});
