import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useStudents } from "../../api/hooks/useStudents";
import { anonymisiereName } from "../../utils/anonymize";
import { StudentList } from "./StudentList";

vi.mock("../../api/hooks/useStudents");

const mockUseStudents = vi.mocked(useStudents);

function renderList(initialEntries: string[] = ["/schueler"]) {
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <StudentList />
    </MemoryRouter>,
  );
}

const BASE_STUDENT = {
  id: 1,
  vorname: "Max",
  nachname: "Muster",
  klasse: { id: 1, name: "10a" },
  zaehlerstand: {
    fehlzeiten: { aktueller_stand: 4, erreichte_stufe_nr: 1 },
    klassenbuch: { aktueller_stand: 0, erreichte_stufe_nr: null },
  },
  letzte_benachrichtigung: null,
  ohne_massnahme_seit_benachrichtigung: false,
  fehltage: { gesamt: 3, entschuldigt: 2, unentschuldigt: 1 },
  fehlstunden: { gesamt: 1.5, entschuldigt: 1.0, unentschuldigt: 0.5 },
  klassenbuch_anzahl: 2,
};

function mockData(items: unknown[], overrides: Record<string, unknown> = {}) {
  mockUseStudents.mockReturnValue({
    data: { items, total: items.length, limit: 50, offset: 0 },
    isLoading: false,
    isError: false,
    ...overrides,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
  } as any);
}

describe("StudentList", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("hides the Anonymisieren toggle and ignores ?a=1 when VITE_ANONYMISIERUNG_AKTIV is unset", () => {
    mockData([BASE_STUDENT]);

    renderList(["/schueler?a=1"]);

    expect(screen.queryByLabelText("Anonymisieren")).not.toBeInTheDocument();
    expect(screen.getByText("Muster, Max")).toBeInTheDocument();
  });

  it("renders a row per student with a link to the detail page", () => {
    mockData([BASE_STUDENT]);

    renderList();

    expect(screen.getByRole("link", { name: /Muster, Max/ })).toHaveAttribute("href", "/schueler/1");
    expect(screen.getByText("10a")).toBeInTheDocument();
  });

  it("replaces the student name with an anonymized one when ?a=1 is set, and carries the param into the detail link", () => {
    vi.stubEnv("VITE_ANONYMISIERUNG_AKTIV", "true");
    mockData([BASE_STUDENT]);

    renderList(["/schueler?a=1"]);

    const fakeName = anonymisiereName(BASE_STUDENT.id);
    expect(screen.queryByText(/Muster, Max/)).not.toBeInTheDocument();
    const link = screen.getByRole("link", { name: new RegExp(`${fakeName.nachname}, ${fakeName.vorname}`) });
    expect(link).toHaveAttribute("href", "/schueler/1?a=1");
  });

  it("shows Fehltage/Fehlstunden/Eintraege as their gesamt values, always (both modes)", () => {
    mockData([BASE_STUDENT]);

    renderList();

    const row = screen.getByRole("row", { name: /Muster, Max/ });
    expect(within(row).getByText("3")).toBeInTheDocument(); // Fehltage gesamt
    expect(within(row).getByText("1.5")).toBeInTheDocument(); // Fehlstunden gesamt
    expect(within(row).getByText("2")).toBeInTheDocument(); // Eintraege
  });

  it("shows the entschuldigt/unentschuldigt split as a title tooltip on the Fehltage cell", () => {
    mockData([BASE_STUDENT]);

    renderList();

    const row = screen.getByRole("row", { name: /Muster, Max/ });
    const fehltageCell = within(row).getByText("3");
    expect(fehltageCell).toHaveAttribute("title", expect.stringContaining("2 entschuldigt"));
    expect(fehltageCell).toHaveAttribute("title", expect.stringContaining("1 unentschuldigt"));
  });

  it("highlights a row without a measure since the last notification", () => {
    mockData([{ ...BASE_STUDENT, ohne_massnahme_seit_benachrichtigung: true }]);

    renderList();

    expect(screen.getByRole("row", { name: /Muster, Max/ })).toHaveAttribute("data-highlighted", "true");
  });

  it("toggles the nur_auffaellige filter via the URL params", () => {
    mockData([]);

    renderList();
    fireEvent.click(screen.getByLabelText("Nur auffällige"));

    expect(mockUseStudents).toHaveBeenLastCalledWith(expect.objectContaining({ nurAuffaellige: true }));
  });

  it("toggles anonymization via the URL params without a full page navigation", () => {
    vi.stubEnv("VITE_ANONYMISIERUNG_AKTIV", "true");
    mockData([BASE_STUDENT]);

    renderList();
    expect(screen.getByText("Muster, Max")).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText("Anonymisieren"));

    const fakeName = anonymisiereName(BASE_STUDENT.id);
    expect(screen.queryByText("Muster, Max")).not.toBeInTheDocument();
    expect(screen.getByText(`${fakeName.nachname}, ${fakeName.vorname}`)).toBeInTheDocument();
  });

  it("sets the min_stufe filter via the Mindeststufe select", () => {
    mockData([]);

    renderList();
    fireEvent.change(screen.getByLabelText("Mindeststufe"), { target: { value: "2" } });

    expect(mockUseStudents).toHaveBeenLastCalledWith(expect.objectContaining({ minStufe: 2 }));
  });

  it("resets offset back to 0 when a filter changes while paginated", () => {
    mockData([]);

    renderList(["/schueler?offset=50"]);
    fireEvent.click(screen.getByLabelText("Nur auffällige"));

    expect(mockUseStudents).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 0 }));
  });

  it("disables the Weiter button on the last page", () => {
    mockData([BASE_STUDENT]);

    renderList();

    expect(screen.getByRole("button", { name: "Weiter" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Zurück" })).toBeDisabled();
  });

  it("shows an error message when the request fails", () => {
    mockData([], { data: undefined, isError: true });

    renderList();

    expect(screen.getByText("Fehler beim Laden der Schülerliste.")).toBeInTheDocument();
  });

  it("reads schuljahr from the URL and passes it to useStudents", () => {
    mockData([]);

    renderList(["/schueler?schuljahr=27"]);

    expect(mockUseStudents).toHaveBeenLastCalledWith(expect.objectContaining({ schuljahrId: 27 }));
  });

  it("hides zaehlerstand-based columns (Eskalationsstufe, Benachrichtigt) in history mode", () => {
    mockData([{ ...BASE_STUDENT, zaehlerstand: null, letzte_benachrichtigung: null }]);

    renderList(["/schueler?schuljahr=27"]);

    expect(screen.queryByText("Benachrichtigt")).not.toBeInTheDocument();
  });

  it("sorts by clicking a column header, toggling asc/desc, and persists it in the URL", () => {
    mockData([]);

    renderList();
    fireEvent.click(screen.getByRole("columnheader", { name: /Fehlstunden/ }));

    expect(mockUseStudents).toHaveBeenLastCalledWith(
      expect.objectContaining({ sortBy: "fehlstunden", sortDir: "asc" }),
    );

    fireEvent.click(screen.getByRole("columnheader", { name: /Fehlstunden/ }));

    expect(mockUseStudents).toHaveBeenLastCalledWith(
      expect.objectContaining({ sortBy: "fehlstunden", sortDir: "desc" }),
    );
  });
  describe("Trend-Pfeile", () => {
    const TREND = {
      fehltage: { aktuell: 3, vorher: 1, richtung: "steigend" },
      fehlstunden: { aktuell: 2, vorher: 9, richtung: "fallend" },
    };

    it.each([
      ["steigend", "↗", "trendSteigend"],
      ["gleich", "→", "trendGleich"],
      ["fallend", "↘", "trendFallend"],
    ])("shows the %s arrow shape, color class and raw numbers as tooltip behind Fehltage", (richtung, pfeil, klasse) => {
      mockData([{ ...BASE_STUDENT, trend: { ...TREND, fehltage: { aktuell: 3, vorher: 1, richtung } } }]);

      renderList(["/schueler?trend_tage=7"]);

      const row = screen.getByRole("row", { name: /Muster, Max/ });
      const arrow = within(row).getAllByRole("img")[0];
      expect(arrow).toHaveTextContent(pfeil);
      expect(arrow).toHaveAttribute("data-richtung", richtung);
      expect(arrow.className).toContain(klasse);
      expect(arrow).toHaveAttribute("title", "Letzte 7 Tage: 3, davor: 1");
      expect(arrow).toHaveAccessibleName(expect.stringContaining(richtung));
    });

    it("shows a separate arrow behind Fehlstunden with its own numbers", () => {
      mockData([{ ...BASE_STUDENT, trend: TREND }]);

      renderList(["/schueler?trend_tage=14"]);

      const arrows = within(screen.getByRole("row", { name: /Muster, Max/ })).getAllByRole("img");
      expect(arrows).toHaveLength(2);
      expect(arrows[0]).toHaveTextContent("↗");
      expect(arrows[1]).toHaveTextContent("↘");
      expect(arrows[1]).toHaveAttribute("title", "Letzte 14 Tage: 2, davor: 9");
    });

    it("shows no arrow when richtung is null", () => {
      mockData([
        {
          ...BASE_STUDENT,
          trend: {
            fehltage: { aktuell: 3, vorher: 0, richtung: null },
            fehlstunden: { aktuell: 0, vorher: 0, richtung: null },
          },
        },
      ]);

      renderList(["/schueler?trend_tage=7"]);

      expect(screen.queryAllByRole("img")).toHaveLength(0);
    });

    it("shows no arrow without trend data", () => {
      mockData([BASE_STUDENT]);

      renderList();

      expect(screen.queryAllByRole("img")).toHaveLength(0);
    });

    it("keeps the existing split tooltip on the value cell", () => {
      mockData([{ ...BASE_STUDENT, trend: TREND }]);

      renderList(["/schueler?trend_tage=7"]);

      const cell = within(screen.getByRole("row", { name: /Muster, Max/ })).getByText("3");
      expect(cell).toHaveAttribute("title", expect.stringContaining("2 entschuldigt"));
    });

    it("passes trend_tage from the URL to useStudents, and null by default or for invalid values", () => {
      mockData([]);
      renderList(["/schueler?trend_tage=30"]);
      expect(mockUseStudents).toHaveBeenLastCalledWith(expect.objectContaining({ trendTage: 30 }));

      renderList(["/schueler?trend_tage=5"]);
      expect(mockUseStudents).toHaveBeenLastCalledWith(expect.objectContaining({ trendTage: null }));
    });

    it("triggers a request with trend_tage via the Trend-Zeitraum select and can switch it off", () => {
      mockData([]);

      renderList();
      expect(screen.getByLabelText("Trend-Zeitraum")).toHaveValue("");
      fireEvent.change(screen.getByLabelText("Trend-Zeitraum"), { target: { value: "14" } });
      expect(mockUseStudents).toHaveBeenLastCalledWith(expect.objectContaining({ trendTage: 14 }));

      fireEvent.change(screen.getByLabelText("Trend-Zeitraum"), { target: { value: "" } });
      expect(mockUseStudents).toHaveBeenLastCalledWith(expect.objectContaining({ trendTage: null }));
    });

    it("hides the Trend-Zeitraum select and sends no trend in history mode", () => {
      mockData([]);

      renderList(["/schueler?schuljahr=27&trend_tage=7"]);

      expect(screen.queryByLabelText("Trend-Zeitraum")).not.toBeInTheDocument();
      expect(mockUseStudents).toHaveBeenLastCalledWith(expect.objectContaining({ trendTage: null }));
    });
  });
});
