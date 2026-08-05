import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { useStudents } from "../../api/hooks/useStudents";
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
  it("renders a row per student with a link to the detail page", () => {
    mockData([BASE_STUDENT]);

    renderList();

    expect(screen.getByRole("link", { name: /Muster, Max/ })).toHaveAttribute("href", "/schueler/1");
    expect(screen.getByText("10a")).toBeInTheDocument();
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
});
