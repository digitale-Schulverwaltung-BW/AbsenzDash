import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { useAbteilungen } from "../../api/hooks/useAbteilungen";
import { useThresholdRules } from "../../api/hooks/useThresholdRules";
import { useUpdateThresholdRules } from "../../api/hooks/useUpdateThresholdRules";
import { ThresholdRules } from "./ThresholdRules";

vi.mock("../../api/hooks/useThresholdRules");
vi.mock("../../api/hooks/useUpdateThresholdRules");
vi.mock("../../api/hooks/useAbteilungen");

describe("ThresholdRules", () => {
  it("renders an existing schulweite Regel with its Stufen", () => {
    vi.mocked(useThresholdRules).mockReturnValue({
      data: [
        {
          id: 1, typ: "fehlzeiten", geltungsbereich: "schulweit", abteilung_id: null,
          stufen: [{ id: 1, stufe_nr: 1, einheit: "fehltage", schwellenwert: 4, fehlzeiten_filter: "nur_unentschuldigt", empfaenger_rollen: ["klassenlehrkraft"] }],
        },
      ],
      isLoading: false,
      isError: false,
    } as any);
    vi.mocked(useUpdateThresholdRules).mockReturnValue({ mutate: vi.fn(), isPending: false, error: null } as any);
    vi.mocked(useAbteilungen).mockReturnValue({ data: [], isLoading: false, isError: false } as any);

    render(<ThresholdRules />);
    expect(screen.getByDisplayValue("4")).toBeInTheDocument();
    expect(screen.getByLabelText("klassenlehrkraft Regel 1 Stufe 1")).toBeChecked();
  });

  it("shows the Abteilung dropdown only when geltungsbereich is abteilung", async () => {
    vi.mocked(useThresholdRules).mockReturnValue({
      data: [{ id: 1, typ: "fehlzeiten", geltungsbereich: "schulweit", abteilung_id: null, stufen: [] }],
      isLoading: false,
      isError: false,
    } as any);
    vi.mocked(useUpdateThresholdRules).mockReturnValue({ mutate: vi.fn(), isPending: false, error: null } as any);
    vi.mocked(useAbteilungen).mockReturnValue({
      data: [{ id: 5, name: "Kaufmännisch" }],
      isLoading: false,
      isError: false,
    } as any);

    render(<ThresholdRules />);
    expect(screen.queryByLabelText("Abteilung Regel 1")).not.toBeInTheDocument();

    await userEvent.selectOptions(screen.getByLabelText("Geltungsbereich Regel 1"), "abteilung");
    expect(screen.getByLabelText("Abteilung Regel 1")).toBeInTheDocument();
    expect(screen.getByText("Kaufmännisch")).toBeInTheDocument();
  });

  it("adds and removes a Stufe", async () => {
    vi.mocked(useThresholdRules).mockReturnValue({
      data: [{ id: 1, typ: "fehlzeiten", geltungsbereich: "schulweit", abteilung_id: null, stufen: [] }],
      isLoading: false,
      isError: false,
    } as any);
    vi.mocked(useUpdateThresholdRules).mockReturnValue({ mutate: vi.fn(), isPending: false, error: null } as any);
    vi.mocked(useAbteilungen).mockReturnValue({ data: [], isLoading: false, isError: false } as any);

    render(<ThresholdRules />);
    await userEvent.click(screen.getByText("Stufe hinzufügen"));
    expect(screen.getByText("Stufe 1")).toBeInTheDocument();

    await userEvent.click(screen.getByText("Stufe entfernen"));
    expect(screen.queryByText("Stufe 1")).not.toBeInTheDocument();
  });

  it("renumbers stufe_nr sequentially after removing a non-trailing Stufe and adding a new one", async () => {
    vi.mocked(useThresholdRules).mockReturnValue({
      data: [{ id: 1, typ: "fehlzeiten", geltungsbereich: "schulweit", abteilung_id: null, stufen: [] }],
      isLoading: false,
      isError: false,
    } as any);
    vi.mocked(useUpdateThresholdRules).mockReturnValue({ mutate: vi.fn(), isPending: false, error: null } as any);
    vi.mocked(useAbteilungen).mockReturnValue({ data: [], isLoading: false, isError: false } as any);

    render(<ThresholdRules />);

    // Build up two Stufen: "Stufe 1" and "Stufe 2".
    await userEvent.click(screen.getByText("Stufe hinzufügen"));
    await userEvent.click(screen.getByText("Stufe hinzufügen"));
    expect(screen.getByText("Stufe 1")).toBeInTheDocument();
    expect(screen.getByText("Stufe 2")).toBeInTheDocument();

    // Remove the FIRST Stufe (not the trailing one) — the survivor previously
    // kept its stale stufe_nr of 2 here, which then collided with a newly
    // added Stufe's freshly computed stufe_nr of 2.
    await userEvent.click(screen.getAllByText("Stufe entfernen")[0]);
    expect(screen.queryByText("Stufe 2")).not.toBeInTheDocument();
    expect(screen.getByText("Stufe 1")).toBeInTheDocument();

    // Add a new Stufe — it must not collide with the renumbered survivor.
    await userEvent.click(screen.getByText("Stufe hinzufügen"));
    expect(screen.getAllByText("Stufe 1")).toHaveLength(1);
    expect(screen.getAllByText("Stufe 2")).toHaveLength(1);
    expect(screen.queryByText("Stufe 3")).not.toBeInTheDocument();
  });
});
