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
            typ: "verspaetung",
            datum: "2026-02-01",
            start_zeit: 1,
            end_zeit: 1,
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
  });

  it("shows 'ganztägig' for typ='tag' instead of the start_zeit/end_zeit range", () => {
    render(
      <FehlzeitenTable
        fehlzeiten={[
          {
            id: 1,
            typ: "tag",
            datum: "2026-02-01",
            start_zeit: 0,
            end_zeit: 2359,
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
            typ: "verspaetung",
            datum: "2026-02-01",
            start_zeit: 1,
            end_zeit: 1,
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
