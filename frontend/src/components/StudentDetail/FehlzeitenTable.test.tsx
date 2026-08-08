import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { FehlzeitenTable } from "./FehlzeitenTable";

describe("FehlzeitenTable", () => {
  it("resolves excuse_status_id to its long_name", () => {
    render(
      <FehlzeitenTable
        fehlzeiten={[
          {
            id: 1,
            typ: "stunde",
            datum: "2026-02-01",
            start_zeit: 1,
            end_zeit: 1,
            dauer_anzeige: "15 Minuten (Stunde 1)",
            fach: "Mathe",
            excuse_status_id: 5,
            grund_text: null,
          },
        ]}
        excuseStatuses={[{ id: 5, name: "E", long_name: "Entschuldigt" }]}
      />,
    );

    expect(screen.getByText("Entschuldigt")).toBeInTheDocument();
    expect(screen.getByText("Mathe")).toBeInTheDocument();
    expect(screen.getByText("15 Minuten (Stunde 1)")).toBeInTheDocument();
  });

  it("shows the backend-provided dauer_anzeige label as-is", () => {
    render(
      <FehlzeitenTable
        fehlzeiten={[
          {
            id: 1,
            typ: "tag",
            datum: "2026-02-01",
            start_zeit: 0,
            end_zeit: 2359,
            dauer_anzeige: "ganztägig",
            fach: null,
            excuse_status_id: null,
            grund_text: null,
          },
        ]}
        excuseStatuses={[]}
      />,
    );

    expect(screen.getByText("ganztägig")).toBeInTheDocument();
    expect(screen.queryByText("0–2359")).not.toBeInTheDocument();
  });

  it("shows a dash when excuse_status_id is null", () => {
    render(
      <FehlzeitenTable
        fehlzeiten={[
          {
            id: 1,
            typ: "stunde",
            datum: "2026-02-01",
            start_zeit: 1,
            end_zeit: 1,
            dauer_anzeige: "0 Minuten (Stunde 1)",
            fach: null,
            excuse_status_id: null,
            grund_text: null,
          },
        ]}
        excuseStatuses={[]}
      />,
    );

    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });
});
