import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { StatsVergleichEintrag } from "../../api/types";
import { ComparisonChart } from "./ComparisonChart";

const beispielEintrag: StatsVergleichEintrag = {
  id: 1,
  name: "AME56",
  anzahl_schueler: 20,
  avg_fehltage: 2,
  avg_fehlstunden: 3,
  avg_klassenbuch: 1,
  anzahl_klassenbuch: 20,
  anzahl_massnahmen: 2,
};

describe("ComparisonChart", () => {
  it("renders nothing when there is no comparison data", () => {
    const { container } = render(<ComparisonChart data={[]} metric="avg_fehltage" />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders a chart container when comparison data is present", () => {
    const { container } = render(<ComparisonChart data={[beispielEintrag]} metric="avg_fehltage" />);
    expect(container.querySelector(".recharts-responsive-container")).not.toBeNull();
  });

  it("renders without error when onEntryClick is provided", () => {
    const { container } = render(
      <ComparisonChart data={[beispielEintrag]} metric="avg_fehltage" onEntryClick={() => {}} />,
    );
    expect(container.querySelector(".recharts-responsive-container")).not.toBeNull();
  });
});

// Die tatsaechliche Balkenfarbe/den Klick-Handler pro Balken kann jsdom nicht pruefen: recharts'
// ResponsiveContainer rendert erst bei einer echten ResizeObserver-Groesse (siehe src/test/setup.ts),
// die in jsdom nie eintrifft. Farblogik ist stattdessen in colorScale.test.ts abgedeckt, die
// Bereich-vs-Klasse-Klick-Entscheidung in entryClickTarget.test.ts.
