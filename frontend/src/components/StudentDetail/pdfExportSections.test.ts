import { describe, expect, it } from "vitest";
import { ALL_SECTIONS, buildSectionsParam } from "./pdfExportSections";

describe("ALL_SECTIONS", () => {
  it("lists the five backend section values", () => {
    expect(ALL_SECTIONS).toEqual(["fehlzeiten", "klassenbuch", "massnahmen", "ausnahmen", "benachrichtigungen"]);
  });
});

describe("buildSectionsParam", () => {
  it("returns undefined when every section is selected (matches backend default)", () => {
    expect(buildSectionsParam(new Set(ALL_SECTIONS))).toBeUndefined();
  });

  it("returns a comma-joined list when only some sections are selected", () => {
    expect(buildSectionsParam(new Set(["fehlzeiten", "massnahmen"]))).toBe("fehlzeiten,massnahmen");
  });

  it("returns an empty string when nothing is selected", () => {
    expect(buildSectionsParam(new Set())).toBe("");
  });
});
