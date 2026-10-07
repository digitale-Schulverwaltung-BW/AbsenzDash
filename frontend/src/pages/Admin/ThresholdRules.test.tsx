import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAbteilungen } from "../../api/hooks/useAbteilungen";
import { useThresholdCoverage } from "../../api/hooks/useThresholdCoverage";
import { useThresholdRules } from "../../api/hooks/useThresholdRules";
import { useUpdateThresholdRules } from "../../api/hooks/useUpdateThresholdRules";
import { ThresholdRules } from "./ThresholdRules";

vi.mock("../../api/hooks/useThresholdRules");
vi.mock("../../api/hooks/useUpdateThresholdRules");
vi.mock("../../api/hooks/useAbteilungen");
vi.mock("../../api/hooks/useThresholdCoverage");

beforeEach(() => {
  vi.mocked(useThresholdCoverage).mockReturnValue({ data: [], isLoading: false, isError: false } as any);
});

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

  it("creates a new Klassenbuch rule with a Stufe whose fehlzeiten-only fields are null (regression: 422)", async () => {
    vi.mocked(useThresholdRules).mockReturnValue({
      data: [],
      isLoading: false,
      isError: false,
    } as any);
    const mutate = vi.fn();
    vi.mocked(useUpdateThresholdRules).mockReturnValue({ mutate, isPending: false, error: null } as any);
    vi.mocked(useAbteilungen).mockReturnValue({ data: [], isLoading: false, isError: false } as any);

    render(<ThresholdRules />);

    await userEvent.click(screen.getByText("Neue Regel"));
    await userEvent.selectOptions(screen.getByLabelText("Typ Regel 1"), "klassenbuch");
    await userEvent.click(screen.getByText("Stufe hinzufügen"));
    await userEvent.click(screen.getByLabelText("klassenlehrkraft Regel 1 Stufe 1"));
    await userEvent.click(screen.getByLabelText("klassenlehrkraft Regel 1 Stufe 2"));

    await userEvent.click(screen.getByText("Speichern"));

    expect(mutate).toHaveBeenCalledTimes(1);
    const rules = mutate.mock.calls[0][0];
    expect(rules[0].typ).toBe("klassenbuch");
    expect(rules[0].stufen[0].einheit).toBeNull();
    expect(rules[0].stufen[0].fehlzeiten_filter).toBeNull();
  });

  it("clears einheit/fehlzeiten_filter on existing Stufen when switching an existing rule's Typ to Klassenbuch (regression: 422)", async () => {
    vi.mocked(useThresholdRules).mockReturnValue({
      data: [
        {
          id: 1, typ: "fehlzeiten", geltungsbereich: "schulweit", abteilung_id: null,
          stufen: [{ id: 1, stufe_nr: 1, einheit: "fehltage", schwellenwert: 4, fehlzeiten_filter: "nur_unentschuldigt", empfaenger_rollen: [] }],
        },
      ],
      isLoading: false,
      isError: false,
    } as any);
    const mutate = vi.fn();
    vi.mocked(useUpdateThresholdRules).mockReturnValue({ mutate, isPending: false, error: null } as any);
    vi.mocked(useAbteilungen).mockReturnValue({ data: [], isLoading: false, isError: false } as any);

    render(<ThresholdRules />);

    await userEvent.selectOptions(screen.getByLabelText("Typ Regel 1"), "klassenbuch");
    await userEvent.click(screen.getByLabelText("klassenlehrkraft Regel 1 Stufe 1"));
    await userEvent.click(screen.getByText("Speichern"));

    expect(mutate).toHaveBeenCalledTimes(1);
    const rules = mutate.mock.calls[0][0];
    expect(rules[0].typ).toBe("klassenbuch");
    expect(rules[0].stufen[0].einheit).toBeNull();
    expect(rules[0].stufen[0].fehlzeiten_filter).toBeNull();
  });

  it("blocks saving and shows an inline hint when a Stufe has no Empfänger (regression: backend 422)", async () => {
    vi.mocked(useThresholdRules).mockReturnValue({
      data: [{ id: 1, typ: "fehlzeiten", geltungsbereich: "schulweit", abteilung_id: null, stufen: [] }],
      isLoading: false,
      isError: false,
    } as any);
    const mutate = vi.fn();
    vi.mocked(useUpdateThresholdRules).mockReturnValue({ mutate, isPending: false, error: null } as any);
    vi.mocked(useAbteilungen).mockReturnValue({ data: [], isLoading: false, isError: false } as any);

    render(<ThresholdRules />);

    await userEvent.click(screen.getByText("Stufe hinzufügen"));
    expect(screen.queryByText("Bitte mindestens einen Empfänger auswählen.")).not.toBeInTheDocument();

    await userEvent.click(screen.getByText("Speichern"));

    expect(mutate).not.toHaveBeenCalled();
    expect(screen.getByText("Bitte mindestens einen Empfänger auswählen.")).toBeInTheDocument();

    await userEvent.click(screen.getByLabelText("klassenlehrkraft Regel 1 Stufe 1"));
    expect(screen.queryByText("Bitte mindestens einen Empfänger auswählen.")).not.toBeInTheDocument();

    await userEvent.click(screen.getByText("Speichern"));
    expect(mutate).toHaveBeenCalledTimes(1);
  });

  it("accepts a decimal Schwellenwert (e.g. 5.5) instead of collapsing to 0 (regression: step=1 stepMismatch)", async () => {
    vi.mocked(useThresholdRules).mockReturnValue({
      data: [
        {
          id: 1, typ: "fehlzeiten", geltungsbereich: "schulweit", abteilung_id: null,
          stufen: [{ id: 1, stufe_nr: 1, einheit: "fehlstunden", schwellenwert: 4, fehlzeiten_filter: "nur_unentschuldigt", empfaenger_rollen: ["klassenlehrkraft"] }],
        },
      ],
      isLoading: false,
      isError: false,
    } as any);
    const mutate = vi.fn();
    vi.mocked(useUpdateThresholdRules).mockReturnValue({ mutate, isPending: false, error: null } as any);
    vi.mocked(useAbteilungen).mockReturnValue({ data: [], isLoading: false, isError: false } as any);

    render(<ThresholdRules />);

    const schwellenwertInput = screen.getByLabelText("Schwellenwert Regel 1 Stufe 1");
    fireEvent.change(schwellenwertInput, { target: { value: "5.5" } });

    await userEvent.click(screen.getByText("Speichern"));

    expect(mutate).toHaveBeenCalledTimes(1);
    const rules = mutate.mock.calls[0][0];
    expect(rules[0].stufen[0].schwellenwert).toBe(5.5);
  });

  it("warns when a Typ has no schulweite Regel and Klassen are not covered", () => {
    vi.mocked(useThresholdRules).mockReturnValue({
      data: [{ id: 1, typ: "fehlzeiten", geltungsbereich: "abteilung", abteilung_id: 16, stufen: [] }],
      isLoading: false,
      isError: false,
    } as any);
    vi.mocked(useUpdateThresholdRules).mockReturnValue({ mutate: vi.fn(), isPending: false, error: null } as any);
    vi.mocked(useAbteilungen).mockReturnValue({ data: [], isLoading: false, isError: false } as any);
    vi.mocked(useThresholdCoverage).mockReturnValue({
      data: [
        { typ: "fehlzeiten", hat_schulweite_regel: false, klassen_ohne_regel: 12 },
        { typ: "klassenbuch", hat_schulweite_regel: true, klassen_ohne_regel: 0 },
      ],
    } as any);

    render(<ThresholdRules />);

    expect(
      screen.getByText(
        "Für Fehlzeiten gibt es keine schulweite Regel; 12 Klassen haben keine Regel und werden nicht eskaliert.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Für Klassenbuch/)).not.toBeInTheDocument();
  });

  it("shows no coverage warning when every Klasse is covered", () => {
    vi.mocked(useThresholdRules).mockReturnValue({ data: [], isLoading: false, isError: false } as any);
    vi.mocked(useUpdateThresholdRules).mockReturnValue({ mutate: vi.fn(), isPending: false, error: null } as any);
    vi.mocked(useAbteilungen).mockReturnValue({ data: [], isLoading: false, isError: false } as any);
    vi.mocked(useThresholdCoverage).mockReturnValue({
      data: [{ typ: "fehlzeiten", hat_schulweite_regel: false, klassen_ohne_regel: 0 }],
    } as any);

    render(<ThresholdRules />);

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
