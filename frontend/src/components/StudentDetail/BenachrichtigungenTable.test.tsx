import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { BenachrichtigungenTable } from "./BenachrichtigungenTable";

describe("BenachrichtigungenTable", () => {
  it("lists recipients for a sent notification", () => {
    render(
      <BenachrichtigungenTable
        benachrichtigungen={[
          {
            id: 1,
            regel_id: 1,
            typ: "fehlzeiten",
            stufe_nr: 1,
            gesendet_am: "2026-02-01T00:00:00Z",
            empfaenger: [{ rolle: "klassenlehrkraft", name: "A. Beispiel" }],
            status: "gesendet",
          },
        ]}
      />,
    );

    expect(screen.getByText("fehlzeiten")).toBeInTheDocument();
    expect(screen.getByText("klassenlehrkraft: A. Beispiel")).toBeInTheDocument();
  });

  it("shows a status text when there are no recipients", () => {
    render(
      <BenachrichtigungenTable
        benachrichtigungen={[
          {
            id: 1,
            regel_id: 1,
            typ: "fehlzeiten",
            stufe_nr: 1,
            gesendet_am: "2026-02-01T00:00:00Z",
            empfaenger: [],
            status: "kein_empfaenger",
          },
        ]}
      />,
    );

    expect(screen.getByText("Kein Empfänger ermittelbar")).toBeInTheDocument();
  });
});
