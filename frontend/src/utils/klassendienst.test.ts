import { describe, expect, it } from "vitest";
import { klassendienstStatus, klassendienstText } from "./klassendienst";

const BASIS = { bezeichnung: "Entschuldigungspflicht", beschreibung: null, von: "2026-09-28" };

describe("klassendienstText", () => {
  it("includes the explanation when present", () => {
    expect(klassendienstText({ ...BASIS, beschreibung: "Schriftliche Entschuldigung nötig" })).toBe(
      "Entschuldigungspflicht: Schriftliche Entschuldigung nötig – seit 28.09.2026",
    );
  });

  it("omits the explanation when empty or blank", () => {
    expect(klassendienstText(BASIS)).toBe("Entschuldigungspflicht – seit 28.09.2026");
    expect(klassendienstText({ ...BASIS, beschreibung: "  " })).toBe("Entschuldigungspflicht – seit 28.09.2026");
  });
});

describe("klassendienstStatus", () => {
  const heute = "2026-10-08";
  it("is aktiv when aktiv_heute is set", () => {
    expect(klassendienstStatus({ aktiv_heute: true, von: "2026-09-28", bis: "2027-07-26" }, heute)).toBe("aktiv");
  });
  it("is zukünftig when von lies after today", () => {
    expect(klassendienstStatus({ aktiv_heute: false, von: "2026-11-02", bis: "2026-11-08" }, heute)).toBe("zukünftig");
  });
  it("is beendet when bis lies before today", () => {
    expect(klassendienstStatus({ aktiv_heute: false, von: "2026-09-14", bis: "2026-09-20" }, heute)).toBe("beendet");
  });
});
