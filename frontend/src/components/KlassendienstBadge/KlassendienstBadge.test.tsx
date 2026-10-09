import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Klassendienst } from "../../api/types";
import { KlassendienstBadges } from "./KlassendienstBadge";

const DIENST: Klassendienst = {
  typ_id: 1,
  kuerzel: "E",
  bezeichnung: "Entschuldigungspflicht",
  beschreibung: "Schriftliche Entschuldigung nötig",
  von: "2026-09-28",
  bis: "2027-07-26",
  aktiv_heute: true,
};

describe("KlassendienstBadges", () => {
  it("shows the Kürzel with title and aria-label including explanation and German date", () => {
    render(<KlassendienstBadges klassendienste={[DIENST]} />);
    const badge = screen.getByRole("img", {
      name: "Entschuldigungspflicht: Schriftliche Entschuldigung nötig – seit 28.09.2026",
    });
    expect(badge).toHaveTextContent("E");
    expect(badge).toHaveAttribute("title", "Entschuldigungspflicht: Schriftliche Entschuldigung nötig – seit 28.09.2026");
  });

  it("omits the explanation when empty", () => {
    render(<KlassendienstBadges klassendienste={[{ ...DIENST, beschreibung: null }]} />);
    expect(screen.getByRole("img", { name: "Entschuldigungspflicht – seit 28.09.2026" })).toBeInTheDocument();
  });

  it("renders one badge per active service", () => {
    render(
      <KlassendienstBadges
        klassendienste={[DIENST, { ...DIENST, typ_id: 2, kuerzel: "A", bezeichnung: "Attestpflicht", beschreibung: null }]}
      />,
    );
    expect(screen.getAllByRole("img")).toHaveLength(2);
  });

  it("renders nothing without services, with undefined or only inactive ones", () => {
    const { container, rerender } = render(<KlassendienstBadges klassendienste={[]} />);
    expect(container).toBeEmptyDOMElement();
    rerender(<KlassendienstBadges klassendienste={undefined} />);
    expect(container).toBeEmptyDOMElement();
    rerender(<KlassendienstBadges klassendienste={[{ ...DIENST, aktiv_heute: false }]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
