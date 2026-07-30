import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { useStudentCatalog } from "../../api/hooks/useStudentCatalog";
import { useStudentDetail } from "../../api/hooks/useStudentDetail";
import { StudentDetail } from "./StudentDetail";

vi.mock("../../api/hooks/useStudentDetail");
vi.mock("../../api/hooks/useStudentCatalog");
vi.mock("../../api/hooks/useCreateMeasure", () => ({
  useCreateMeasure: () => ({ mutate: vi.fn(), isPending: false, error: null }),
}));
vi.mock("../../api/hooks/useCreateExemption", () => ({
  useCreateExemption: () => ({ mutate: vi.fn(), isPending: false, error: null }),
}));
vi.mock("../../api/hooks/useRevokeExemption", () => ({
  useRevokeExemption: () => ({ mutate: vi.fn(), isPending: false }),
}));

const mockUseStudentDetail = vi.mocked(useStudentDetail);
const mockUseStudentCatalog = vi.mocked(useStudentCatalog);

const CATALOG = { massnahmen_typen: [{ id: 1, name: "Gespräch" }], excuse_statuses: [], classreg_categories: [] };

const DETAIL = {
  id: 7,
  vorname: "Max",
  nachname: "Muster",
  klasse: { id: 1, name: "10a" },
  zaehlerstand: {
    fehlzeiten: { aktueller_stand: 4, erreichte_stufe_nr: 1 },
    klassenbuch: { aktueller_stand: 0, erreichte_stufe_nr: null },
  },
  fehlzeiten: [],
  klassenbuch: [],
  massnahmen: [],
  ausnahmen: [],
  benachrichtigungen: [],
};

function renderDetail() {
  return render(
    <MemoryRouter initialEntries={["/schueler/7"]}>
      <Routes>
        <Route path="/schueler/:id" element={<StudentDetail />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("StudentDetail", () => {
  it("renders the student header and all sections", () => {
    mockUseStudentDetail.mockReturnValue({ data: DETAIL, isLoading: false, isError: false } as any); // eslint-disable-line @typescript-eslint/no-explicit-any
    mockUseStudentCatalog.mockReturnValue({ data: CATALOG, isLoading: false, isError: false } as any); // eslint-disable-line @typescript-eslint/no-explicit-any

    renderDetail();

    expect(screen.getByText("Muster, Max")).toBeInTheDocument();
    expect(screen.getByText("10a")).toBeInTheDocument();
    expect(screen.getByText("Maßnahmen")).toBeInTheDocument();
    expect(screen.getByText("Ausnahmen")).toBeInTheDocument();
  });

  it("shows an error message when the detail request fails", () => {
    mockUseStudentDetail.mockReturnValue({ data: undefined, isLoading: false, isError: true } as any); // eslint-disable-line @typescript-eslint/no-explicit-any
    mockUseStudentCatalog.mockReturnValue({ data: CATALOG, isLoading: false, isError: false } as any); // eslint-disable-line @typescript-eslint/no-explicit-any

    renderDetail();

    expect(screen.getByText("Fehler beim Laden des Schülers.")).toBeInTheDocument();
  });

  it("passes the schuljahr URL param through to useStudentDetail and hides the Zählerstand badges when in history mode", () => {
    mockUseStudentDetail.mockReturnValue({
      data: { ...DETAIL, zaehlerstand: {} },
      isLoading: false,
      isError: false,
    } as any); // eslint-disable-line @typescript-eslint/no-explicit-any
    mockUseStudentCatalog.mockReturnValue({ data: CATALOG, isLoading: false, isError: false } as any); // eslint-disable-line @typescript-eslint/no-explicit-any

    render(
      <MemoryRouter initialEntries={["/schueler/7?schuljahr=27"]}>
        <Routes>
          <Route path="/schueler/:id" element={<StudentDetail />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(mockUseStudentDetail).toHaveBeenLastCalledWith(7, 27);
    expect(screen.queryByText(/Fehlzeiten: /)).not.toBeInTheDocument();
  });
});
