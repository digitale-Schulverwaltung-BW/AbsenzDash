import { describe, expect, it } from "vitest";
import { kuerzelVorschlag, validateKlassendienstTypen } from "./klassendienstValidation";
import type { KlassendienstDraft } from "./klassendienstValidation";

const OK: KlassendienstDraft = {
  webuntis_dienst_id: 26,
  bezeichnung: "Entschuldigungspflicht",
  kuerzel: "E",
  beschreibung: "",
  aktiv: true,
};

describe("validateKlassendienstTypen", () => {
  it("accepts a valid list", () => {
    expect(validateKlassendienstTypen([OK, { ...OK, webuntis_dienst_id: 27 }])).toEqual([]);
  });

  it("rejects missing, zero, negative and fractional dienst ids", () => {
    for (const id of [null, 0, -1, 1.5]) {
      const errors = validateKlassendienstTypen([{ ...OK, webuntis_dienst_id: id }]);
      expect(errors.map((e) => e.feld)).toEqual(["webuntis_dienst_id"]);
    }
  });

  it("rejects duplicate dienst ids on the second row", () => {
    const errors = validateKlassendienstTypen([OK, { ...OK }]);
    expect(errors).toEqual([expect.objectContaining({ rowIndex: 1, feld: "webuntis_dienst_id" })]);
  });

  it("rejects empty and too long bezeichnung", () => {
    expect(validateKlassendienstTypen([{ ...OK, bezeichnung: "  " }])[0].feld).toBe("bezeichnung");
    expect(validateKlassendienstTypen([{ ...OK, bezeichnung: "x".repeat(101) }])[0].feld).toBe("bezeichnung");
    expect(validateKlassendienstTypen([{ ...OK, bezeichnung: "x".repeat(100) }])).toEqual([]);
  });

  it("rejects empty and too long kuerzel", () => {
    expect(validateKlassendienstTypen([{ ...OK, kuerzel: "" }])[0].feld).toBe("kuerzel");
    expect(validateKlassendienstTypen([{ ...OK, kuerzel: "x".repeat(11) }])[0].feld).toBe("kuerzel");
    expect(validateKlassendienstTypen([{ ...OK, kuerzel: "x".repeat(10) }])).toEqual([]);
  });

  it("rejects too long beschreibung", () => {
    expect(validateKlassendienstTypen([{ ...OK, beschreibung: "x".repeat(301) }])[0].feld).toBe("beschreibung");
    expect(validateKlassendienstTypen([{ ...OK, beschreibung: "x".repeat(300) }])).toEqual([]);
  });
});

describe("kuerzelVorschlag", () => {
  it("uses the uppercased first letter", () => {
    expect(kuerzelVorschlag("entschuldigungspflicht")).toBe("E");
    expect(kuerzelVorschlag("  Pflicht zur Vorlage")).toBe("P");
    expect(kuerzelVorschlag("")).toBe("");
  });
});
