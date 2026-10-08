import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/client";
import { useKlassendienstTypen } from "../../api/hooks/useKlassendienstTypen";
import { useUpdateKlassendienstTypen } from "../../api/hooks/useUpdateKlassendienstTypen";
import { useWebuntisDienstOptionen } from "../../api/hooks/useWebuntisDienstOptionen";
import { KlassendienstTypen } from "./KlassendienstTypen";

vi.mock("../../api/hooks/useKlassendienstTypen");
vi.mock("../../api/hooks/useUpdateKlassendienstTypen");
vi.mock("../../api/hooks/useWebuntisDienstOptionen");

const TYP = {
  id: 5,
  webuntis_dienst_id: 26,
  bezeichnung: "Entschuldigungspflicht",
  kuerzel: "E",
  beschreibung: "Schriftliche Entschuldigung nötig",
  aktiv: true,
};

/* eslint-disable @typescript-eslint/no-explicit-any */
function setup({
  typen = [TYP] as unknown[],
  optionen = { optionen: [{ id: 26, bezeichnung: "Entschuldigungspflicht" }, { id: 27, bezeichnung: "Pflicht zur Vorlage ärztl. Atteste" }], hinweis: null } as unknown,
  optionenError = false,
  mutate = vi.fn(),
  error = null as unknown,
} = {}) {
  vi.mocked(useKlassendienstTypen).mockReturnValue({ data: typen, isLoading: false, isError: false } as any);
  vi.mocked(useWebuntisDienstOptionen).mockReturnValue({
    data: optionenError ? undefined : optionen,
    isLoading: false,
    isError: optionenError,
  } as any);
  vi.mocked(useUpdateKlassendienstTypen).mockReturnValue({ mutate, isPending: false, error, isSuccess: false } as any);
  return mutate;
}
/* eslint-enable @typescript-eslint/no-explicit-any */

describe("KlassendienstTypen", () => {
  beforeEach(() => vi.clearAllMocks());

  it("loads and shows existing services and the explanatory note", () => {
    setup();
    render(<KlassendienstTypen />);
    expect(screen.getByDisplayValue("Entschuldigungspflicht")).toBeInTheDocument();
    expect(screen.getByLabelText("Dienst-ID Zeile 1")).toHaveValue(26);
    expect(screen.getByLabelText("Kürzel Zeile 1")).toHaveValue("E");
    expect(screen.getByLabelText("Erklärung Zeile 1")).toHaveValue("Schriftliche Entschuldigung nötig");
    expect(screen.getByText(/Dienst-IDs stammen aus den WebUntis-Stammdaten/)).toBeInTheDocument();
    expect(screen.getByText(/höchstens einmal täglich/)).toBeInTheDocument();
    expect(screen.getByText(/keinen Einfluss auf Zähler, Eskalation/)).toBeInTheDocument();
  });

  it("adds a service from the WebUntis suggestions with a Kürzel suggestion and saves it", async () => {
    const mutate = setup();
    render(<KlassendienstTypen />);
    const select = screen.getByLabelText("Dienst aus WebUntis");
    // 26 ist bereits vergeben und wird nicht mehr angeboten
    expect(screen.queryByRole("option", { name: /26:/ })).not.toBeInTheDocument();
    await userEvent.selectOptions(select, "27");
    expect(screen.getByLabelText("Dienst-ID Zeile 2")).toHaveValue(27);
    expect(screen.getByLabelText("Bezeichnung Zeile 2")).toHaveValue("Pflicht zur Vorlage ärztl. Atteste");
    expect(screen.getByLabelText("Kürzel Zeile 2")).toHaveValue("P");

    await userEvent.clear(screen.getByLabelText("Kürzel Zeile 2"));
    await userEvent.type(screen.getByLabelText("Kürzel Zeile 2"), "A");
    await userEvent.click(screen.getByText("Speichern"));

    expect(mutate).toHaveBeenCalledWith([
      { id: 5, webuntis_dienst_id: 26, bezeichnung: "Entschuldigungspflicht", kuerzel: "E", beschreibung: "Schriftliche Entschuldigung nötig", aktiv: true },
      { webuntis_dienst_id: 27, bezeichnung: "Pflicht zur Vorlage ärztl. Atteste", kuerzel: "A", beschreibung: null, aktiv: true },
    ]);
  });

  it("adds a service manually", async () => {
    const mutate = setup({ typen: [] });
    render(<KlassendienstTypen />);
    await userEvent.click(screen.getByText("Dienst hinzufügen (manuell)"));
    await userEvent.type(screen.getByLabelText("Dienst-ID Zeile 1"), "30");
    await userEvent.type(screen.getByLabelText("Bezeichnung Zeile 1"), " Ordnungsdienst ");
    await userEvent.type(screen.getByLabelText("Kürzel Zeile 1"), "O");
    await userEvent.click(screen.getByText("Speichern"));
    expect(mutate).toHaveBeenCalledWith([
      { webuntis_dienst_id: 30, bezeichnung: "Ordnungsdienst", kuerzel: "O", beschreibung: null, aktiv: true },
    ]);
  });

  it("blocks saving and shows field errors for invalid input", async () => {
    const mutate = setup({ typen: [] });
    render(<KlassendienstTypen />);
    await userEvent.click(screen.getByText("Dienst hinzufügen (manuell)"));
    await userEvent.click(screen.getByText("Speichern"));
    expect(mutate).not.toHaveBeenCalled();
    expect(screen.getByText("Dienst-ID muss eine ganze Zahl ab 1 sein.")).toBeInTheDocument();
    expect(screen.getByText("Bezeichnung darf nicht leer sein.")).toBeInTheDocument();
    expect(screen.getByText("Kürzel darf nicht leer sein.")).toBeInTheDocument();
  });

  it("asks for confirmation before removing a saved service and mentions deactivating", async () => {
    const mutate = setup();
    render(<KlassendienstTypen />);
    await userEvent.click(screen.getByText("Entfernen"));
    expect(screen.getByRole("alertdialog")).toHaveTextContent(/deaktivieren/);
    expect(screen.getByLabelText("Dienst-ID Zeile 1")).toBeInTheDocument();

    await userEvent.click(screen.getByText("Abbrechen"));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Dienst-ID Zeile 1")).toBeInTheDocument();

    await userEvent.click(screen.getByText("Entfernen"));
    await userEvent.click(screen.getByText("Endgültig entfernen"));
    expect(screen.queryByLabelText("Dienst-ID Zeile 1")).not.toBeInTheDocument();
    await userEvent.click(screen.getByText("Speichern"));
    expect(mutate).toHaveBeenCalledWith([]);
  });

  it("removes an unsaved row without confirmation", async () => {
    setup({ typen: [] });
    render(<KlassendienstTypen />);
    await userEvent.click(screen.getByText("Dienst hinzufügen (manuell)"));
    await userEvent.click(screen.getByText("Entfernen"));
    expect(screen.queryByLabelText("Dienst-ID Zeile 1")).not.toBeInTheDocument();
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("shows the backend detail for 422 and 409 errors", () => {
    setup({ error: new ApiError(409, "x", "Dienst-ID 26 existiert bereits") });
    const { unmount } = render(<KlassendienstTypen />);
    expect(screen.getByText("Speichern abgelehnt: Dienst-ID 26 existiert bereits")).toBeInTheDocument();
    unmount();

    setup({ error: new ApiError(422, "x", "kuerzel must not be empty") });
    render(<KlassendienstTypen />);
    expect(screen.getByText("Speichern abgelehnt: kuerzel must not be empty")).toBeInTheDocument();
  });

  it("shows a generic message for other errors", () => {
    setup({ error: new ApiError(500, "x") });
    render(<KlassendienstTypen />);
    expect(screen.getByText("Fehler beim Speichern der Klassendienste.")).toBeInTheDocument();
  });

  it("shows the hint when the suggestion list is empty and keeps manual entry available", () => {
    setup({ optionen: { optionen: [], hinweis: "WebUntis lieferte keine Dienste." } });
    render(<KlassendienstTypen />);
    expect(screen.getByText("WebUntis lieferte keine Dienste.")).toBeInTheDocument();
    expect(screen.getByLabelText("Dienst aus WebUntis")).toBeDisabled();
    expect(screen.getByText("Dienst hinzufügen (manuell)")).toBeEnabled();
  });

  it("shows a fallback hint when the suggestion request itself fails", () => {
    setup({ optionenError: true });
    render(<KlassendienstTypen />);
    expect(screen.getByText(/Vorschlagsliste aus WebUntis konnte nicht geladen werden/)).toBeInTheDocument();
  });
});
