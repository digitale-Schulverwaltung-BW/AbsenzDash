import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Klassendienst } from "../../api/types";
import { KlassendiensteSection } from "./KlassendiensteSection";

const BASIS: Klassendienst = {
  typ_id: 1,
  kuerzel: "E",
  bezeichnung: "Entschuldigungspflicht",
  beschreibung: "Schriftliche Entschuldigung nötig",
  von: "2026-09-28",
  bis: "2027-07-26",
  aktiv_heute: true,
};

describe("KlassendiensteSection", () => {
  it("shows heading, German date range and status aktiv", () => {
    render(<KlassendiensteSection klassendienste={[BASIS]} heute="2026-10-08" />);
    expect(screen.getByRole("heading", { name: "Klassendienste (aus WebUntis, schreibgeschützt)" })).toBeInTheDocument();
    expect(screen.getByText("28.09.2026 – 26.07.2027")).toBeInTheDocument();
    expect(screen.getByText("aktiv")).toBeInTheDocument();
    expect(screen.getByText("Entschuldigungspflicht", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("Schriftliche Entschuldigung nötig")).toBeInTheDocument();
  });

  it("derives zukünftig and beendet from the injected date", () => {
    render(
      <KlassendiensteSection
        heute="2026-10-08"
        klassendienste={[
          { ...BASIS, von: "2026-11-02", bis: "2026-11-08", aktiv_heute: false },
          { ...BASIS, von: "2026-09-07", bis: "2026-09-13", aktiv_heute: false },
        ]}
      />,
    );
    const rows = screen.getAllByRole("row").slice(1);
    expect(within(rows[0]).getByText("zukünftig")).toBeInTheDocument();
    expect(within(rows[1]).getByText("beendet")).toBeInTheDocument();
  });

  it("shows a calm hint when there are none or the field is missing", () => {
    const { rerender } = render(<KlassendiensteSection klassendienste={[]} />);
    expect(screen.getByText("Keine Klassendienste hinterlegt.")).toBeInTheDocument();
    rerender(<KlassendiensteSection klassendienste={undefined} />);
    expect(screen.getByText("Keine Klassendienste hinterlegt.")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});
