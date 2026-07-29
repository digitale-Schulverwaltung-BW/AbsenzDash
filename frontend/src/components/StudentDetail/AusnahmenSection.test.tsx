import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useCreateExemption } from "../../api/hooks/useCreateExemption";
import { useRevokeExemption } from "../../api/hooks/useRevokeExemption";
import { AusnahmenSection } from "./AusnahmenSection";

vi.mock("../../api/hooks/useCreateExemption");
vi.mock("../../api/hooks/useRevokeExemption");

const mockUseCreateExemption = vi.mocked(useCreateExemption);
const mockUseRevokeExemption = vi.mocked(useRevokeExemption);

describe("AusnahmenSection", () => {
  it("renders active and inactive Ausnahmen and offers an Aufheben button only for active ones", () => {
    mockUseCreateExemption.mockReturnValue({ mutate: vi.fn(), isPending: false, isSuccess: false, error: null } as any); // eslint-disable-line @typescript-eslint/no-explicit-any
    mockUseRevokeExemption.mockReturnValue({ mutate: vi.fn(), isPending: false } as any); // eslint-disable-line @typescript-eslint/no-explicit-any

    render(
      <AusnahmenSection
        studentId={7}
        ausnahmen={[
          { id: 1, kategorie: "fehlzeiten", grund: "Attest", gueltig_bis: null, aktiv: true },
          { id: 2, kategorie: "klassenbuch", grund: "Alt", gueltig_bis: "2026-01-01", aktiv: false },
        ]}
      />,
    );

    expect(screen.getByText("Attest")).toBeInTheDocument();
    expect(screen.getByText("Alt")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Aufheben" })).toHaveLength(1);
  });

  it("calls revoke mutation when Aufheben is clicked", () => {
    const revokeMutate = vi.fn();
    mockUseCreateExemption.mockReturnValue({ mutate: vi.fn(), isPending: false, isSuccess: false, error: null } as any); // eslint-disable-line @typescript-eslint/no-explicit-any
    mockUseRevokeExemption.mockReturnValue({ mutate: revokeMutate, isPending: false } as any); // eslint-disable-line @typescript-eslint/no-explicit-any

    render(
      <AusnahmenSection
        studentId={7}
        ausnahmen={[{ id: 1, kategorie: "fehlzeiten", grund: "Attest", gueltig_bis: null, aktiv: true }]}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Aufheben" }));
    expect(revokeMutate).toHaveBeenCalledWith(1);
  });

  it("submits the create form with the chosen kategorie, grund and gueltig_bis", async () => {
    const createMutate = vi.fn();
    mockUseCreateExemption.mockReturnValue({ mutate: createMutate, isPending: false, isSuccess: false, error: null } as any); // eslint-disable-line @typescript-eslint/no-explicit-any
    mockUseRevokeExemption.mockReturnValue({ mutate: vi.fn(), isPending: false } as any); // eslint-disable-line @typescript-eslint/no-explicit-any

    render(<AusnahmenSection studentId={7} ausnahmen={[]} />);

    fireEvent.click(screen.getByLabelText("Klassenbuch"));
    fireEvent.change(screen.getByLabelText("Grund"), { target: { value: "Attest" } });
    fireEvent.change(screen.getByLabelText("Gültig bis"), { target: { value: "2026-08-01" } });
    fireEvent.click(screen.getByRole("button", { name: "Ausnahme setzen" }));

    await waitFor(() =>
      expect(createMutate).toHaveBeenCalledWith({ kategorie: "klassenbuch", grund: "Attest", gueltig_bis: "2026-08-01" }),
    );
  });
});
