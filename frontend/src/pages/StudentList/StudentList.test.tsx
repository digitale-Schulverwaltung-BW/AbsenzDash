import { fireEvent, render, screen } from "@testing-library/react";
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
};

describe("StudentList", () => {
  it("renders a row per student with a link to the detail page", () => {
    mockUseStudents.mockReturnValue({
      data: { items: [BASE_STUDENT], total: 1, limit: 50, offset: 0 },
      isLoading: false,
      isError: false,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);

    renderList();

    expect(screen.getByRole("link", { name: /Muster, Max/ })).toHaveAttribute("href", "/schueler/1");
    expect(screen.getByText("10a")).toBeInTheDocument();
  });

  it("highlights a row without a measure since the last notification", () => {
    mockUseStudents.mockReturnValue({
      data: {
        items: [{ ...BASE_STUDENT, ohne_massnahme_seit_benachrichtigung: true }],
        total: 1,
        limit: 50,
        offset: 0,
      },
      isLoading: false,
      isError: false,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);

    renderList();

    expect(screen.getByRole("row", { name: /Muster, Max/ })).toHaveAttribute("data-highlighted", "true");
  });

  it("toggles the nur_auffaellige filter via the URL params", () => {
    mockUseStudents.mockReturnValue({
      data: { items: [], total: 0, limit: 50, offset: 0 },
      isLoading: false,
      isError: false,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);

    renderList();
    fireEvent.click(screen.getByLabelText("Nur auffällige"));

    expect(mockUseStudents).toHaveBeenLastCalledWith(
      expect.objectContaining({ nurAuffaellige: true }),
    );
  });

  it("sets the min_stufe filter via the Mindeststufe select", () => {
    mockUseStudents.mockReturnValue({
      data: { items: [], total: 0, limit: 50, offset: 0 },
      isLoading: false,
      isError: false,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);

    renderList();
    fireEvent.change(screen.getByLabelText("Mindeststufe"), { target: { value: "2" } });

    expect(mockUseStudents).toHaveBeenLastCalledWith(expect.objectContaining({ minStufe: 2 }));
  });

  it("resets offset back to 0 when a filter changes while paginated", () => {
    mockUseStudents.mockReturnValue({
      data: { items: [], total: 0, limit: 50, offset: 0 },
      isLoading: false,
      isError: false,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);

    renderList(["/schueler?offset=50"]);
    fireEvent.click(screen.getByLabelText("Nur auffällige"));

    expect(mockUseStudents).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 0 }));
  });

  it("disables the Weiter button on the last page", () => {
    mockUseStudents.mockReturnValue({
      data: { items: [BASE_STUDENT], total: 1, limit: 50, offset: 0 },
      isLoading: false,
      isError: false,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);

    renderList();

    expect(screen.getByRole("button", { name: "Weiter" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Zurück" })).toBeDisabled();
  });

  it("shows an error message when the request fails", () => {
    mockUseStudents.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);

    renderList();

    expect(screen.getByText("Fehler beim Laden der Schülerliste.")).toBeInTheDocument();
  });
});
