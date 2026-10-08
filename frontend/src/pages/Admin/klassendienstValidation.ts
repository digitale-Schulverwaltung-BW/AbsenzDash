export interface KlassendienstDraft {
  id?: number | null;
  webuntis_dienst_id: number | null;
  bezeichnung: string;
  kuerzel: string;
  beschreibung: string;
  aktiv: boolean;
}

export type KlassendienstFeld = "webuntis_dienst_id" | "bezeichnung" | "kuerzel" | "beschreibung";

export interface KlassendienstValidationError {
  rowIndex: number;
  feld: KlassendienstFeld;
  message: string;
}

export const MAX_BEZEICHNUNG = 100;
export const MAX_KUERZEL = 10;
export const MAX_BESCHREIBUNG = 300;

/** Spiegelt die Backend-Validierung (`PUT /admin/klassendienst-typen`), damit Fehler vor dem Roundtrip auffallen. */
export function validateKlassendienstTypen(rows: KlassendienstDraft[]): KlassendienstValidationError[] {
  const errors: KlassendienstValidationError[] = [];
  const gesehen = new Map<number, number>();
  rows.forEach((row, rowIndex) => {
    const dienstId = row.webuntis_dienst_id;
    if (dienstId === null || !Number.isInteger(dienstId) || dienstId < 1) {
      errors.push({ rowIndex, feld: "webuntis_dienst_id", message: "Dienst-ID muss eine ganze Zahl ab 1 sein." });
    } else if (gesehen.has(dienstId)) {
      errors.push({ rowIndex, feld: "webuntis_dienst_id", message: "Diese Dienst-ID ist bereits eingetragen." });
    } else {
      gesehen.set(dienstId, rowIndex);
    }
    const bezeichnung = row.bezeichnung.trim();
    if (bezeichnung === "") {
      errors.push({ rowIndex, feld: "bezeichnung", message: "Bezeichnung darf nicht leer sein." });
    } else if (bezeichnung.length > MAX_BEZEICHNUNG) {
      errors.push({ rowIndex, feld: "bezeichnung", message: `Bezeichnung höchstens ${MAX_BEZEICHNUNG} Zeichen.` });
    }
    const kuerzel = row.kuerzel.trim();
    if (kuerzel === "") {
      errors.push({ rowIndex, feld: "kuerzel", message: "Kürzel darf nicht leer sein." });
    } else if (kuerzel.length > MAX_KUERZEL) {
      errors.push({ rowIndex, feld: "kuerzel", message: `Kürzel höchstens ${MAX_KUERZEL} Zeichen.` });
    }
    if (row.beschreibung.length > MAX_BESCHREIBUNG) {
      errors.push({ rowIndex, feld: "beschreibung", message: `Erklärung höchstens ${MAX_BESCHREIBUNG} Zeichen.` });
    }
  });
  return errors;
}

/** Kürzel-Vorschlag: erster Buchstabe der Bezeichnung in Großbuchstaben. */
export function kuerzelVorschlag(bezeichnung: string): string {
  const erster = bezeichnung.trim().charAt(0);
  return erster.toLocaleUpperCase("de-DE");
}
