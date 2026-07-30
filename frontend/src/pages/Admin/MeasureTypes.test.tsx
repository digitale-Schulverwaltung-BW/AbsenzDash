import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { useMeasureTypes } from "../../api/hooks/useMeasureTypes";
import { useUpdateMeasureTypes } from "../../api/hooks/useUpdateMeasureTypes";
import { MeasureTypes } from "./MeasureTypes";

vi.mock("../../api/hooks/useMeasureTypes");
vi.mock("../../api/hooks/useUpdateMeasureTypes");

describe("MeasureTypes", () => {
  it("renders existing types and adds a new row", async () => {
    vi.mocked(useMeasureTypes).mockReturnValue({
      data: [{ id: 1, name: "Nachsitzen", setzt_zaehler_zurueck: true, aktiv: true }],
      isLoading: false,
      isError: false,
    } as any);
    vi.mocked(useUpdateMeasureTypes).mockReturnValue({ mutate: vi.fn(), isPending: false, error: null } as any);

    render(<MeasureTypes />);
    expect(screen.getByDisplayValue("Nachsitzen")).toBeInTheDocument();

    await userEvent.click(screen.getByText("Neuer Maßnahmen-Typ"));
    expect(screen.getByLabelText("Name Zeile 2")).toBeInTheDocument();
  });

  it("submits the full edited list on Speichern", async () => {
    const updateMutate = vi.fn();
    vi.mocked(useMeasureTypes).mockReturnValue({
      data: [{ id: 1, name: "Gespräch", setzt_zaehler_zurueck: false, aktiv: true }],
      isLoading: false,
      isError: false,
    } as any);
    vi.mocked(useUpdateMeasureTypes).mockReturnValue({ mutate: updateMutate, isPending: false, error: null } as any);

    render(<MeasureTypes />);
    await userEvent.click(screen.getByLabelText("Setzt Zähler zurück Zeile 1"));
    await userEvent.click(screen.getByText("Speichern"));

    expect(updateMutate).toHaveBeenCalledWith([
      { id: 1, name: "Gespräch", setzt_zaehler_zurueck: true, aktiv: true },
    ]);
  });
});
