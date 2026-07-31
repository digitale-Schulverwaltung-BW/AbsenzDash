import { describe, expect, it } from "vitest";
import { resolveEntryClickTarget } from "./entryClickTarget";

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
