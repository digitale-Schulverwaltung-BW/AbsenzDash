import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { NotificationFlyout } from "./NotificationFlyout";

describe("NotificationFlyout", () => {
  it("shows a neutral badge and no flyout content when there is no notification", () => {
    render(<NotificationFlyout benachrichtigung={null} />);
    expect(screen.getByText("Keine Benachrichtigung")).toBeInTheDocument();
  });

  it("lists recipients for a sent notification", () => {
    render(
      <NotificationFlyout
        benachrichtigung={{
          id: 1,
          regel_id: 1,
          typ: "fehlzeiten",
          stufe_nr: 1,
          gesendet_am: "2026-02-01T00:00:00Z",
          empfaenger: [{ rolle: "klassenlehrkraft", name: "A. Beispiel" }],
          status: "gesendet",
        }}
      />,
    );
    expect(screen.getByText("Benachrichtigt")).toBeInTheDocument();
    expect(screen.getByText("klassenlehrkraft: A. Beispiel")).toBeInTheDocument();
  });

  it("shows a status text instead of recipients when no recipient could be determined", () => {
    render(
      <NotificationFlyout
        benachrichtigung={{
          id: 1,
          regel_id: 1,
          typ: "fehlzeiten",
          stufe_nr: 1,
          gesendet_am: "2026-02-01T00:00:00Z",
          empfaenger: [],
          status: "kein_empfaenger",
        }}
      />,
    );
    expect(screen.getByText("Kein Empfänger ermittelbar")).toBeInTheDocument();
  });

  it("shows a status text for notifications carried over from the initial import", () => {
    render(
      <NotificationFlyout
        benachrichtigung={{
          id: 1,
          regel_id: 1,
          typ: "fehlzeiten",
          stufe_nr: 1,
          gesendet_am: "2026-02-01T00:00:00Z",
          empfaenger: [],
          status: "initial_import",
        }}
      />,
    );
    expect(screen.getByText("Aus initialem Datenimport übernommen")).toBeInTheDocument();
  });
});
