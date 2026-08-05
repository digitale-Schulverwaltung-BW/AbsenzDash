import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiDownload } from "../../api/client";
import { useNavOptions } from "../../api/hooks/useNavOptions";
import { PdfExportSection } from "./PdfExportSection";

vi.mock("../../api/client");
vi.mock("../../api/hooks/useNavOptions");

const mockApiDownload = vi.mocked(apiDownload);
const mockUseNavOptions = vi.mocked(useNavOptions);

function mockNavOptions() {
  mockUseNavOptions.mockReturnValue({
    data: {
      bereiche: [],
      klassen: [],
      rolle: "klassenlehrkraft",
      schuljahre: [{ id: 27, name: "2024/2025", start_datum: "2024-09-09", end_datum: "2025-07-30" }],
      aktuelles_schuljahr_id: null,
    },
    isLoading: false,
    isError: false,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
  } as any);
}

// URL.createObjectURL/revokeObjectURL don't exist in jsdom.
beforeEach(() => {
  window.URL.createObjectURL = vi.fn().mockReturnValue("blob:mock");
  window.URL.revokeObjectURL = vi.fn();
});

describe("PdfExportSection", () => {
  it("renders five checkboxes, all checked by default", () => {
    mockNavOptions();
    render(<PdfExportSection studentId={1} schuljahrId={null} />);

    for (const label of ["Fehlzeiten", "Klassenbuch", "Maßnahmen", "Ausnahmen", "Benachrichtigungen"]) {
      expect(screen.getByLabelText(label)).toBeChecked();
    }
  });

  it("blocks export and shows an inline hint when every checkbox is unchecked", async () => {
    mockNavOptions();
    render(<PdfExportSection studentId={1} schuljahrId={null} />);

    for (const label of ["Fehlzeiten", "Klassenbuch", "Maßnahmen", "Ausnahmen", "Benachrichtigungen"]) {
      await userEvent.click(screen.getByLabelText(label));
    }
    await userEvent.click(screen.getByText("PDF exportieren"));

    expect(mockApiDownload).not.toHaveBeenCalled();
    expect(screen.getByText("Bitte mindestens einen Abschnitt auswählen.")).toBeInTheDocument();
  });

  it("downloads without a sections param and without schuljahr_id when everything is default", async () => {
    mockNavOptions();
    mockApiDownload.mockResolvedValue({ blob: new Blob(["%PDF"]), filename: "export.pdf" });
    render(<PdfExportSection studentId={1} schuljahrId={null} />);

    await userEvent.click(screen.getByText("PDF exportieren"));

    await waitFor(() => expect(mockApiDownload).toHaveBeenCalledWith("students/1/export.pdf"));
  });

  it("includes schuljahr_id and shows the resolved Schuljahr name when one is selected", async () => {
    mockNavOptions();
    mockApiDownload.mockResolvedValue({ blob: new Blob(["%PDF"]), filename: "export.pdf" });
    render(<PdfExportSection studentId={1} schuljahrId={27} />);

    expect(screen.getByText("Export für Schuljahr 2024/2025")).toBeInTheDocument();

    await userEvent.click(screen.getByLabelText("Benachrichtigungen"));
    await userEvent.click(screen.getByText("PDF exportieren"));

    await waitFor(() =>
      expect(mockApiDownload).toHaveBeenCalledWith(
        "students/1/export.pdf?sections=fehlzeiten,klassenbuch,massnahmen,ausnahmen&schuljahr_id=27",
      ),
    );
  });

  it("shows an error message when the download fails", async () => {
    mockNavOptions();
    mockApiDownload.mockRejectedValue(new Error("boom"));
    render(<PdfExportSection studentId={1} schuljahrId={null} />);

    await userEvent.click(screen.getByText("PDF exportieren"));

    await waitFor(() => expect(screen.getByText("Fehler beim Export — bitte erneut versuchen.")).toBeInTheDocument());
  });
});
