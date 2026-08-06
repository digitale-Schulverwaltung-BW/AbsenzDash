import { describe, expect, it } from "vitest";
import { anonymisiereName, istAnonymisierungAktiv } from "./anonymize";

describe("anonymisiereName", () => {
  it("returns the same name for the same id on repeated calls", () => {
    expect(anonymisiereName(42)).toEqual(anonymisiereName(42));
  });

  it("returns a non-empty vorname and nachname", () => {
    const name = anonymisiereName(1);
    expect(name.vorname.length).toBeGreaterThan(0);
    expect(name.nachname.length).toBeGreaterThan(0);
  });

  it("cycles through the name pool for ids beyond the pool size", () => {
    const poolGroesse = 12; // Anzahl der Eintraege in der festen Namensliste
    expect(anonymisiereName(0)).toEqual(anonymisiereName(poolGroesse));
  });
});

describe("istAnonymisierungAktiv", () => {
  it("is true when a=1 is set", () => {
    expect(istAnonymisierungAktiv(new URLSearchParams("a=1"))).toBe(true);
  });

  it("is false when a is absent or not exactly 1", () => {
    expect(istAnonymisierungAktiv(new URLSearchParams(""))).toBe(false);
    expect(istAnonymisierungAktiv(new URLSearchParams("a=0"))).toBe(false);
    expect(istAnonymisierungAktiv(new URLSearchParams("a=true"))).toBe(false);
  });
});
