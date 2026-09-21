import { useState } from "react";
import { useNavOptions } from "../../api/hooks/useNavOptions";
import { useSchuljahrHistorieImportPreview } from "../../api/hooks/useSchuljahrHistorieImportPreview";
import { useSchuljahrHistorieImport } from "../../api/hooks/useSchuljahrHistorieImport";
import styles from "../../components/StudentDetail/StudentDetail.module.css";

export function SchuljahrImport() {
  const { data: navOptions } = useNavOptions();
  const [schuljahrId, setSchuljahrId] = useState<number | null>(null);
  const [file, setFile] = useState<File | null>(null);

  const {
    mutate: preview,
    data: previewResult,
    isPending: isPreviewing,
    error: previewError,
    reset: resetPreview,
  } = useSchuljahrHistorieImportPreview();
  const {
    mutate: confirmImport,
    data: importResult,
    isPending: isImporting,
    error: importError,
  } = useSchuljahrHistorieImport();

  const handlePreview = (event: React.FormEvent) => {
    event.preventDefault();
    if (schuljahrId === null || !file) {
      return;
    }
    preview({ schuljahrId, file });
  };

  const handleConfirm = () => {
    if (schuljahrId === null || !file) {
      return;
    }
    confirmImport({ schuljahrId, file });
  };

  return (
    <section className={styles.section}>
      <h3>Schuljahr-Import (rückwirkend)</h3>
      <p>
        Lädt eine archivierte ASV-BW-CSV für ein vergangenes Schuljahr hoch und ergänzt daraus die
        Klassenzugehörigkeits-Historie. Ändert nie die aktuellen Stammdaten (Name, aktive Klasse) bestehender
        Schüler.
      </p>
      <form
        className={styles.form}
        onSubmit={handlePreview}
        onChange={() => {
          resetPreview();
        }}
      >
        <label>
          Schuljahr
          <select
            aria-label="Schuljahr"
            value={schuljahrId ?? ""}
            onChange={(event) => setSchuljahrId(event.target.value ? Number(event.target.value) : null)}
            required
          >
            <option value="">Bitte wählen</option>
            {navOptions?.schuljahre.map((sj) => (
              <option key={sj.id} value={sj.id}>
                {sj.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          ASV-CSV-Datei
          <input
            aria-label="ASV-CSV-Datei"
            type="file"
            accept=".csv"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          />
        </label>
        <button type="submit" disabled={isPreviewing || schuljahrId === null || !file}>
          Vorschau laden
        </button>
        {previewError && <p className={styles.formError}>Vorschau fehlgeschlagen.</p>}
      </form>

      {previewResult && (
        <div>
          <h4>Vorschau</h4>
          <ul>
            <li>Zeilen gesamt: {previewResult.zeilen_gesamt}</li>
            <li>Bereits bekannte Schüler: {previewResult.schueler_bekannt}</li>
            <li>Neue Schüler: {previewResult.schueler_neu}</li>
            <li>Übersprungene Zeilen: {previewResult.uebersprungene_zeilen}</li>
            <li>
              Unbekannte Klassen:{" "}
              {previewResult.unbekannte_klassen.length > 0 ? previewResult.unbekannte_klassen.join(", ") : "keine"}
            </li>
          </ul>
          <button type="button" onClick={handleConfirm} disabled={isImporting}>
            Import bestätigen
          </button>
          {importError && <p className={styles.formError}>Import fehlgeschlagen.</p>}
        </div>
      )}

      {importResult && (
        <div>
          <h4>Ergebnis</h4>
          <ul>
            <li>Zeilen verarbeitet: {importResult.zeilen_verarbeitet}</li>
            <li>Neu angelegte Schüler: {importResult.neu_angelegte_schueler}</li>
            <li>Übersprungene Zeilen: {importResult.uebersprungene_zeilen}</li>
          </ul>
        </div>
      )}
    </section>
  );
}
