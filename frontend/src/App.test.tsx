import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { useNavOptions } from "./api/hooks/useNavOptions";
import { useStats } from "./api/hooks/useStats";
import App from "./App";

vi.mock("./api/hooks/useNavOptions");
vi.mock("./api/hooks/useStats");

const mockUseNavOptions = vi.mocked(useNavOptions);
const mockUseStats = vi.mocked(useStats);

function setupMocks() {
  mockUseNavOptions.mockReturnValue({
    data: { bereiche: [], klassen: [] },
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

  it("renders the Klasse placeholder route", () => {
    setupMocks();
    render(
      <MemoryRouter initialEntries={["/klasse/5"]}>
        <App />
      </MemoryRouter>,
    );
    expect(screen.getByText("Schülerliste folgt in einem späteren Ausbauschritt.")).toBeInTheDocument();
  });

  it("renders the Landing page when mounted under a non-root basename (regression: WordPress page path)", () => {
    // Regression test for the bug where BrowserRouter had no basename: in production the SPA is
    // mounted on a WordPress page at a path like "/absenzdash/", not at "/". App.tsx's routes are
    // declared as absolute paths ("/", "/klasse/:id"), so without a matching basename on the router,
    // <Routes> silently renders nothing on the real deployment even though root-path tests still pass.
    setupMocks();
    render(
      <MemoryRouter basename="/absenzdash" initialEntries={["/absenzdash/"]}>
        <App />
      </MemoryRouter>,
    );
    expect(screen.getByText("Ø Fehltage")).toBeInTheDocument();
  });
});
