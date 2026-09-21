import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { useNavOptions } from "../../api/hooks/useNavOptions";
import { useSchuljahrHistorieImportPreview } from "../../api/hooks/useSchuljahrHistorieImportPreview";
import { useSchuljahrHistorieImport } from "../../api/hooks/useSchuljahrHistorieImport";
import { SchuljahrImport } from "./SchuljahrImport";

vi.mock("../../api/hooks/useNavOptions");
vi.mock("../../api/hooks/useSchuljahrHistorieImportPreview");
vi.mock("../../api/hooks/useSchuljahrHistorieImport");

const NAV_OPTIONS = {
  bereiche: [],
  klassen: [],
  rolle: "schulleitung",
  schuljahre: [
    { id: 28, name: "2025/2026", start_datum: "2025-09-15", end_datum: "2026-07-29" },
    { id: 27, name: "2024/2025", start_datum: "2024-09-09", end_datum: "2025-07-30" },
  ],
  aktuelles_schuljahr_id: 28,
};

describe("SchuljahrImport", () => {
  it("renders a schuljahr dropdown populated from nav-options", () => {
    vi.mocked(useNavOptions).mockReturnValue({ data: NAV_OPTIONS } as any);
    vi.mocked(useSchuljahrHistorieImportPreview).mockReturnValue({
      mutate: vi.fn(),
      data: undefined,
      isPending: false,
      error: null,
      reset: vi.fn(),
    } as any);
    vi.mocked(useSchuljahrHistorieImport).mockReturnValue({
      mutate: vi.fn(),
      data: undefined,
      isPending: false,
      error: null,
    } as any);

    render(<SchuljahrImport />);
    expect(screen.getByText("2025/2026")).toBeInTheDocument();
    expect(screen.getByText("2024/2025")).toBeInTheDocument();
  });

  it("submits schuljahr_id and file to the preview mutation", async () => {
    const previewMutate = vi.fn();
    vi.mocked(useNavOptions).mockReturnValue({ data: NAV_OPTIONS } as any);
    vi.mocked(useSchuljahrHistorieImportPreview).mockReturnValue({
      mutate: previewMutate,
      data: undefined,
      isPending: false,
      error: null,
      reset: vi.fn(),
    } as any);
    vi.mocked(useSchuljahrHistorieImport).mockReturnValue({
      mutate: vi.fn(),
      data: undefined,
      isPending: false,
      error: null,
    } as any);

    render(<SchuljahrImport />);
    await userEvent.selectOptions(screen.getByLabelText("Schuljahr"), "27");
    const file = new File(["inhalt"], "archiv.csv", { type: "text/csv" });
    await userEvent.upload(screen.getByLabelText("ASV-CSV-Datei"), file);
    await userEvent.click(screen.getByText("Vorschau laden"));

    expect(previewMutate).toHaveBeenCalledWith({ schuljahrId: 27, file });
  });

  it("shows the preview summary and a confirm button once preview data is available", async () => {
    const confirmMutate = vi.fn();
    vi.mocked(useNavOptions).mockReturnValue({ data: NAV_OPTIONS } as any);
    vi.mocked(useSchuljahrHistorieImportPreview).mockReturnValue({
      mutate: vi.fn(),
      data: {
        zeilen_gesamt: 10,
        schueler_bekannt: 7,
        schueler_neu: 3,
        unbekannte_klassen: ["XYZ"],
        uebersprungene_zeilen: 1,
      },
      isPending: false,
      error: null,
      reset: vi.fn(),
    } as any);
    vi.mocked(useSchuljahrHistorieImport).mockReturnValue({
      mutate: confirmMutate,
      data: undefined,
      isPending: false,
      error: null,
    } as any);

    render(<SchuljahrImport />);
    // Die Vorschau wird im echten Ablauf erst angezeigt, nachdem schuljahrId/file lokal gesetzt
    // wurden (siehe vorherigen Test) -- fuer "Import bestaetigen" muessen dieselben Werte im
    // Component-State stehen, da preview_import UND commit_import zustandslos sind und die
    // Datei bei BEIDEN Requests erneut mitschicken (Abweichung 9 im Plan).
    await userEvent.selectOptions(screen.getByLabelText("Schuljahr"), "27");
    const file = new File(["inhalt"], "archiv.csv", { type: "text/csv" });
    await userEvent.upload(screen.getByLabelText("ASV-CSV-Datei"), file);

    expect(screen.getByText(/Zeilen gesamt: 10/)).toBeInTheDocument();
    expect(screen.getByText(/XYZ/)).toBeInTheDocument();

    await userEvent.click(screen.getByText("Import bestätigen"));
    expect(confirmMutate).toHaveBeenCalledWith({ schuljahrId: 27, file });
  });
});
