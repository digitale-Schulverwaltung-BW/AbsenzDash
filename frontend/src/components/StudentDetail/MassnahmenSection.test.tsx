import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useCreateMeasure } from "../../api/hooks/useCreateMeasure";
import { MassnahmenSection } from "./MassnahmenSection";

vi.mock("../../api/hooks/useCreateMeasure");

const mockUseCreateMeasure = vi.mocked(useCreateMeasure);

describe("MassnahmenSection", () => {
  it("renders the existing Massnahmen history", () => {
    mockUseCreateMeasure.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);

    render(
      <MassnahmenSection
        studentId={7}
        massnahmen={[
          {
            id: 1,
            massnahmen_typ_id: 2,
            massnahmen_typ_name: "Gespräch",
            datum: "2026-02-01",
            notiz: "Elterngespräch geführt",
            erfasst_von_nutzer_id: 1,
            erfasst_von_name: "A. Beispiel",
          },
        ]}
        massnahmenTypen={[{ id: 2, name: "Gespräch" }]}
      />,
    );

    expect(screen.getByRole("cell", { name: "Gespräch" })).toBeInTheDocument();
    expect(screen.getByText("A. Beispiel")).toBeInTheDocument();
  });

  it("submits the form with the selected type, date and note", async () => {
    const mutate = vi.fn();
    mockUseCreateMeasure.mockReturnValue({
      mutate,
      isPending: false,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);

    render(<MassnahmenSection studentId={7} massnahmen={[]} massnahmenTypen={[{ id: 2, name: "Gespräch" }]} />);

    fireEvent.change(screen.getByLabelText("Typ"), { target: { value: "2" } });
    fireEvent.change(screen.getByLabelText("Datum"), { target: { value: "2026-07-28" } });
    fireEvent.change(screen.getByLabelText("Notiz"), { target: { value: "Testnotiz" } });
    fireEvent.click(screen.getByRole("button", { name: "Maßnahme erfassen" }));

    await waitFor(() =>
      expect(mutate).toHaveBeenCalledWith({ massnahmen_typ_id: 2, datum: "2026-07-28", notiz: "Testnotiz" }),
    );
  });

  it("syncs the selected type once massnahmenTypen arrives after the initial mount (async load-order race)", () => {
    mockUseCreateMeasure.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);

    const { rerender } = render(<MassnahmenSection studentId={7} massnahmen={[]} massnahmenTypen={[]} />);

    rerender(<MassnahmenSection studentId={7} massnahmen={[]} massnahmenTypen={[{ id: 2, name: "Gespräch" }]} />);

    expect(screen.getByLabelText("Typ")).toHaveValue("2");
  });

  it("disables the submit button while the mutation is pending", () => {
    mockUseCreateMeasure.mockReturnValue({
      mutate: vi.fn(),
      isPending: true,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);

    render(<MassnahmenSection studentId={7} massnahmen={[]} massnahmenTypen={[{ id: 2, name: "Gespräch" }]} />);

    expect(screen.getByRole("button", { name: "Maßnahme erfassen" })).toBeDisabled();
  });
});
