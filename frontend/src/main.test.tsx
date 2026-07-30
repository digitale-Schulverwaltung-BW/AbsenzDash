import { screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useNavOptions } from "./api/hooks/useNavOptions";
import { useStats } from "./api/hooks/useStats";

vi.mock("./api/hooks/useNavOptions");
vi.mock("./api/hooks/useStats");

const mockUseNavOptions = vi.mocked(useNavOptions);
const mockUseStats = vi.mocked(useStats);

function setupMocks() {
  mockUseNavOptions.mockReturnValue({
    data: { bereiche: [], klassen: [], rolle: "klassenlehrkraft", schuljahre: [] },
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

// Regression test for the bug where main.tsx mounted <BrowserRouter> with no `basename`. In
// production the SPA is mounted on a WordPress page at a path like "/absenzdash/" (never "/"),
// via window.absenzdashConfig.basename set by wp_localize_script. Without passing that basename
// through to BrowserRouter, React Router matches App.tsx's absolute route paths ("/", "/schueler",
// "/schueler/:id") against the full location.pathname ("/absenzdash/"), which never matches "/" —
// so <Routes> renders nothing and the entire dashboard is a blank page. This test renders through
// the real main.tsx entry point (not a MemoryRouter stand-in) with the browser location actually
// set to a non-root path, so it fails the same way production did if main.tsx regresses.
describe("main.tsx", () => {
  beforeEach(() => {
    setupMocks();
    window.history.pushState({}, "", "/absenzdash/");
    window.absenzdashConfig = {
      restUrl: "/wp-json/absenzdash/v1/api",
      nonce: "test-nonce",
      basename: "/absenzdash",
    };
    const root = document.createElement("div");
    root.id = "absenzdash-root";
    document.body.appendChild(root);
  });

  afterEach(() => {
    document.getElementById("absenzdash-root")?.remove();
    window.history.pushState({}, "", "/");
    delete window.absenzdashConfig;
    vi.resetModules();
  });

  it("renders the Landing page when mounted on a WordPress page at a non-root path", async () => {
    await import("./main");

    await waitFor(() => {
      expect(screen.getByText("Ø Fehltage")).toBeInTheDocument();
    });
  });
});
