import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useNavOptions } from "../../api/hooks/useNavOptions";
import { useStudentCatalog } from "../../api/hooks/useStudentCatalog";
import { useStudentDetail } from "../../api/hooks/useStudentDetail";
import { anonymisiereName } from "../../utils/anonymize";
import { StudentDetail } from "./StudentDetail";

vi.mock("../../api/hooks/useStudentDetail");
vi.mock("../../api/hooks/useStudentCatalog");
vi.mock("../../api/hooks/useNavOptions");
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
const mockUseNavOptions = vi.mocked(useNavOptions);

mockUseNavOptions.mockReturnValue({
  data: { bereiche: [], klassen: [], rolle: "klassenlehrkraft", schuljahre: [], aktuelles_schuljahr_id: null },
  isLoading: false,
  isError: false,
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
} as any);

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
  fehltage: { gesamt: 3, entschuldigt: 2, unentschuldigt: 1 },
  fehlstunden: { gesamt: 1.5, entschuldigt: 1, unentschuldigt: 0.5 },
  klassenbuch_anzahl: 2,
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
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("renders the student header and all sections", () => {
    mockUseStudentDetail.mockReturnValue({ data: DETAIL, isLoading: false, isError: false } as any); // eslint-disable-line @typescript-eslint/no-explicit-any
    mockUseStudentCatalog.mockReturnValue({ data: CATALOG, isLoading: false, isError: false } as any); // eslint-disable-line @typescript-eslint/no-explicit-any

    renderDetail();

    expect(screen.getByText("Muster, Max")).toBeInTheDocument();
    expect(screen.getByText("10a")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Maßnahmen" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Ausnahmen" })).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument(); // Fehltage gesamt
    expect(screen.getByText("1.5")).toBeInTheDocument(); // Fehlstunden gesamt
    expect(screen.getByText("2")).toBeInTheDocument(); // Klassenbuch-Einträge
  });

  it("shows the Klassendienste section with an entry", () => {
    mockUseStudentDetail.mockReturnValue({
      data: {
        ...DETAIL,
        klassendienste: [
          {
            typ_id: 1,
            kuerzel: "E",
            bezeichnung: "Entschuldigungspflicht",
            beschreibung: null,
            von: "2026-09-28",
            bis: "2027-07-26",
            aktiv_heute: true,
          },
        ],
      },
      isLoading: false,
      isError: false,
    } as any); // eslint-disable-line @typescript-eslint/no-explicit-any
    mockUseStudentCatalog.mockReturnValue({ data: CATALOG, isLoading: false, isError: false } as any); // eslint-disable-line @typescript-eslint/no-explicit-any

    renderDetail();

    expect(screen.getByRole("heading", { name: "Klassendienste (aus WebUntis, schreibgeschützt)" })).toBeInTheDocument();
    expect(screen.getByText("28.09.2026 – 26.07.2027")).toBeInTheDocument();
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

  it("replaces the student name with an anonymized one when ?a=1 is set", () => {
    vi.stubEnv("VITE_ANONYMISIERUNG_AKTIV", "true");
    mockUseStudentDetail.mockReturnValue({ data: DETAIL, isLoading: false, isError: false } as any); // eslint-disable-line @typescript-eslint/no-explicit-any
    mockUseStudentCatalog.mockReturnValue({ data: CATALOG, isLoading: false, isError: false } as any); // eslint-disable-line @typescript-eslint/no-explicit-any

    render(
      <MemoryRouter initialEntries={["/schueler/7?a=1"]}>
        <Routes>
          <Route path="/schueler/:id" element={<StudentDetail />} />
        </Routes>
      </MemoryRouter>,
    );

    const fakeName = anonymisiereName(DETAIL.id);
    expect(screen.queryByText("Muster, Max")).not.toBeInTheDocument();
    expect(screen.getByText(`${fakeName.nachname}, ${fakeName.vorname}`)).toBeInTheDocument();
  });

  it("ignores ?a=1 and shows the real name when VITE_ANONYMISIERUNG_AKTIV is unset", () => {
    mockUseStudentDetail.mockReturnValue({ data: DETAIL, isLoading: false, isError: false } as any); // eslint-disable-line @typescript-eslint/no-explicit-any
    mockUseStudentCatalog.mockReturnValue({ data: CATALOG, isLoading: false, isError: false } as any); // eslint-disable-line @typescript-eslint/no-explicit-any

    render(
      <MemoryRouter initialEntries={["/schueler/7?a=1"]}>
        <Routes>
          <Route path="/schueler/:id" element={<StudentDetail />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.getByText("Muster, Max")).toBeInTheDocument();
  });
});
