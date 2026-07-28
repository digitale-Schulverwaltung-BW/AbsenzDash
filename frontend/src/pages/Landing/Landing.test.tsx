import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { useStats } from "../../api/hooks/useStats";
import { Landing } from "./Landing";

vi.mock("../../api/hooks/useStats");

const mockUseStats = vi.mocked(useStats);

describe("Landing", () => {
  it("renders the stat cards from the stats response", () => {
    mockUseStats.mockReturnValue({
      data: {
        level: "schule",
        context: { bereich_id: null, bereich_name: null, klasse_id: null, klasse_name: null },
        own: {
          anzahl_schueler: 100,
          avg_fehltage: 2.5,
          avg_fehlstunden: 1.2,
          avg_klassenbuch: 0.4,
          anzahl_klassenbuch: 40,
          anzahl_massnahmen: 10,
        },
        vergleich: [],
      },
      isLoading: false,
      isError: false,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);

    render(
      <MemoryRouter>
        <Landing />
      </MemoryRouter>,
    );

    expect(screen.getByText("Ø Fehltage")).toBeInTheDocument();
    expect(screen.getByText("2.5")).toBeInTheDocument();
    expect(screen.getByText("Maßnahmen")).toBeInTheDocument();
    expect(screen.getByText("10")).toBeInTheDocument();
    expect(screen.getByText("Schulweit")).toBeInTheDocument();
  });

  it("shows the Klasse name as the scope label when the response is scoped to a Klasse", () => {
    mockUseStats.mockReturnValue({
      data: {
        level: "klasse",
        context: { bereich_id: null, bereich_name: null, klasse_id: 7, klasse_name: "5a" },
        own: {
          anzahl_schueler: 25,
          avg_fehltage: 2.5,
          avg_fehlstunden: 1.2,
          avg_klassenbuch: 0.4,
          anzahl_klassenbuch: 10,
          anzahl_massnahmen: 3,
        },
        vergleich: [],
      },
      isLoading: false,
      isError: false,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);

    render(
      <MemoryRouter>
        <Landing />
      </MemoryRouter>,
    );

    expect(screen.getByText("5a")).toBeInTheDocument();
  });

  it("shows an error message when the stats request fails", () => {
    mockUseStats.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);

    render(
      <MemoryRouter>
        <Landing />
      </MemoryRouter>,
    );

    expect(screen.getByText("Fehler beim Laden der Kennzahlen.")).toBeInTheDocument();
  });
});
