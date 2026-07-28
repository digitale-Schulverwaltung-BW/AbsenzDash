import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { useNavOptions } from "../../api/hooks/useNavOptions";
import { Navigation } from "./Navigation";

vi.mock("../../api/hooks/useNavOptions");

const mockUseNavOptions = vi.mocked(useNavOptions);

function renderNavigation(initialEntries: string[] = ["/"]) {
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <Navigation />
    </MemoryRouter>,
  );
}

describe("Navigation", () => {
  it("shows no dropdowns for a single own Klasse and no Bereiche", () => {
    mockUseNavOptions.mockReturnValue({
      data: { bereiche: [], klassen: [{ id: 1, name: "10a", bereich_id: null }] },
      isLoading: false,
      isError: false,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);

    renderNavigation();

    expect(screen.queryByLabelText("Bereich")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Klasse")).not.toBeInTheDocument();
  });

  it("shows only a Klasse dropdown for multiple own Klassen and no Bereiche", () => {
    mockUseNavOptions.mockReturnValue({
      data: {
        bereiche: [],
        klassen: [
          { id: 1, name: "10a", bereich_id: null },
          { id: 2, name: "10b", bereich_id: null },
        ],
      },
      isLoading: false,
      isError: false,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);

    renderNavigation();

    expect(screen.queryByLabelText("Bereich")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Klasse")).toBeInTheDocument();
  });

  it("shows only a Klasse dropdown, filtered to the single assigned Bereich", () => {
    mockUseNavOptions.mockReturnValue({
      data: {
        bereiche: [{ id: 1, name: "Ausbildung" }],
        klassen: [
          { id: 10, name: "AME56", bereich_id: 1 },
          { id: 11, name: "AME57", bereich_id: 1 },
        ],
      },
      isLoading: false,
      isError: false,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);

    renderNavigation();

    expect(screen.queryByLabelText("Bereich")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Klasse")).toBeInTheDocument();
    expect(screen.getByText("AME56")).toBeInTheDocument();
    expect(screen.getByText("AME57")).toBeInTheDocument();
  });

  it("hides the Klasse dropdown until a Bereich is chosen when there are multiple Bereiche", () => {
    mockUseNavOptions.mockReturnValue({
      data: {
        bereiche: [
          { id: 1, name: "Ausbildung" },
          { id: 2, name: "Berufsschule" },
        ],
        klassen: [
          { id: 10, name: "AME56", bereich_id: 1 },
          { id: 11, name: "BME12", bereich_id: 2 },
        ],
      },
      isLoading: false,
      isError: false,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);

    renderNavigation();

    expect(screen.getByLabelText("Bereich")).toBeInTheDocument();
    expect(screen.queryByLabelText("Klasse")).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Bereich"), { target: { value: "1" } });

    expect(screen.getByLabelText("Klasse")).toBeInTheDocument();
    expect(screen.getByText("AME56")).toBeInTheDocument();
    expect(screen.queryByText("BME12")).not.toBeInTheDocument();
  });
});
