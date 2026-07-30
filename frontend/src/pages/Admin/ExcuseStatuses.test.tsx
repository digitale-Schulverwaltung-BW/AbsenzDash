import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { useExcuseStatuses } from "../../api/hooks/useExcuseStatuses";
import { useUpdateExcuseStatuses } from "../../api/hooks/useUpdateExcuseStatuses";
import { ExcuseStatuses } from "./ExcuseStatuses";

vi.mock("../../api/hooks/useExcuseStatuses");
vi.mock("../../api/hooks/useUpdateExcuseStatuses");

describe("ExcuseStatuses", () => {
  it("renders each status with a checkbox, no name input", () => {
    vi.mocked(useExcuseStatuses).mockReturnValue({
      data: [{ id: 1, name: "nicht entsch.", long_name: null, zaehlt_als_entschuldigt: false, aktiv: true }],
      isLoading: false,
      isError: false,
    } as any);
    vi.mocked(useUpdateExcuseStatuses).mockReturnValue({ mutate: vi.fn(), isPending: false, error: null } as any);

    render(<ExcuseStatuses />);
    expect(screen.getByText("nicht entsch.")).toBeInTheDocument();
    expect(screen.getByLabelText("Entschuldigt: nicht entsch.")).not.toBeChecked();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });

  it("toggles the checkbox and submits the full updated list", async () => {
    const updateMutate = vi.fn();
    vi.mocked(useExcuseStatuses).mockReturnValue({
      data: [{ id: 1, name: "hybrid", long_name: null, zaehlt_als_entschuldigt: false, aktiv: true }],
      isLoading: false,
      isError: false,
    } as any);
    vi.mocked(useUpdateExcuseStatuses).mockReturnValue({ mutate: updateMutate, isPending: false, error: null } as any);

    render(<ExcuseStatuses />);
    await userEvent.click(screen.getByLabelText("Entschuldigt: hybrid"));
    await userEvent.click(screen.getByText("Speichern"));

    expect(updateMutate).toHaveBeenCalledWith([
      { id: 1, name: "hybrid", long_name: null, zaehlt_als_entschuldigt: true, aktiv: true },
    ]);
  });
});
