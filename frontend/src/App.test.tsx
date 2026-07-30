import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { useNavOptions } from "./api/hooks/useNavOptions";
import { useStats } from "./api/hooks/useStats";
import { useStudentCatalog } from "./api/hooks/useStudentCatalog";
import { useStudentDetail } from "./api/hooks/useStudentDetail";
import { useStudents } from "./api/hooks/useStudents";
import App, { RequireSchulleitung } from "./App";

vi.mock("./api/hooks/useNavOptions");
vi.mock("./api/hooks/useStats");
vi.mock("./api/hooks/useStudents");
vi.mock("./api/hooks/useStudentDetail");
vi.mock("./api/hooks/useStudentCatalog");
// StudentDetail renders MassnahmenSection/AusnahmenSection/BenachrichtigungenTable, which call these
// mutation hooks. They need a QueryClient unless mocked directly, so mock them the same way
// StudentDetail.test.tsx does rather than wrapping this test file's tree in a QueryClientProvider.
vi.mock("./api/hooks/useCreateMeasure", () => ({
  useCreateMeasure: () => ({ mutate: vi.fn(), isPending: false, error: null }),
}));
vi.mock("./api/hooks/useCreateExemption", () => ({
  useCreateExemption: () => ({ mutate: vi.fn(), isPending: false, error: null }),
}));
vi.mock("./api/hooks/useRevokeExemption", () => ({
  useRevokeExemption: () => ({ mutate: vi.fn(), isPending: false }),
}));

const mockUseNavOptions = vi.mocked(useNavOptions);
const mockUseStats = vi.mocked(useStats);
const mockUseStudents = vi.mocked(useStudents);
const mockUseStudentDetail = vi.mocked(useStudentDetail);
const mockUseStudentCatalog = vi.mocked(useStudentCatalog);

function setupMocks() {
  mockUseNavOptions.mockReturnValue({
    data: { bereiche: [], klassen: [], rolle: "klassenlehrkraft" },
    isLoading: false,
    isError: false,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
  } as any);
  mockUseStats.mockReturnValue({
    data: {
      level: "schule",
      context: { bereich_id: null, bereich_name: null, klasse_id: null, klasse_name: null },
      own: {
        anzahl_schueler: 0,
        avg_fehltage: 0,
        avg_fehlstunden: 0,
        avg_klassenbuch: 0,
        anzahl_klassenbuch: 0,
        anzahl_massnahmen: 0,
      },
      vergleich: [],
    },
    isLoading: false,
    isError: false,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
  } as any);
  mockUseStudents.mockReturnValue({
    data: { items: [], total: 0, limit: 50, offset: 0 },
    isLoading: false,
    isError: false,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
  } as any);
  mockUseStudentDetail.mockReturnValue({
    data: {
      id: 1,
      vorname: "Max",
      nachname: "Muster",
      klasse: null,
      zaehlerstand: {},
      fehlzeiten: [],
      klassenbuch: [],
      massnahmen: [],
      ausnahmen: [],
      benachrichtigungen: [],
    },
    isLoading: false,
    isError: false,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
  } as any);
  mockUseStudentCatalog.mockReturnValue({
    data: { massnahmen_typen: [], excuse_statuses: [], classreg_categories: [] },
    isLoading: false,
    isError: false,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
  } as any);
}

describe("App", () => {
  it("renders the Landing page at the root route", () => {
    setupMocks();
    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>,
    );
    expect(screen.getByText("Ø Fehltage")).toBeInTheDocument();
  });

  it("renders the Schülerliste route", () => {
    setupMocks();
    render(
      <MemoryRouter initialEntries={["/schueler"]}>
        <App />
      </MemoryRouter>,
    );
    expect(screen.getByText("Name")).toBeInTheDocument();
  });

  it("renders the Schüler-Detail route", () => {
    setupMocks();
    render(
      <MemoryRouter initialEntries={["/schueler/1"]}>
        <App />
      </MemoryRouter>,
    );
    expect(screen.getByText("Muster, Max")).toBeInTheDocument();
  });

  it("renders the Landing page when mounted under a non-root basename (regression: WordPress page path)", () => {
    // Regression test for the bug where BrowserRouter had no basename: in production the SPA is
    // mounted on a WordPress page at a path like "/absenzdash/", not at "/". App.tsx's routes are
    // declared as absolute paths ("/", "/schueler", "/schueler/:id"), so without a matching basename on the router,
    // <Routes> silently renders nothing on the real deployment even though root-path tests still pass.
    setupMocks();
    render(
      <MemoryRouter basename="/absenzdash" initialEntries={["/absenzdash/"]}>
        <App />
      </MemoryRouter>,
    );
    expect(screen.getByText("Ø Fehltage")).toBeInTheDocument();
  });

  it("RequireSchulleitung redirects non-schulleitung users away", () => {
    mockUseNavOptions.mockReturnValue({
      data: { bereiche: [], klassen: [], rolle: "klassenlehrkraft" },
      isLoading: false,
      isError: false,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);
    render(
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route path="/" element={<div>Startseite</div>} />
          <Route path="/geschuetzt" element={<RequireSchulleitung><div>Geheim</div></RequireSchulleitung>} />
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.queryByText("Geheim")).not.toBeInTheDocument();
  });
});
