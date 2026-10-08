import { useEffect, useState } from "react";
import { useKlassendienstTypen } from "../../api/hooks/useKlassendienstTypen";
import { useUpdateKlassendienstTypen } from "../../api/hooks/useUpdateKlassendienstTypen";
import { useWebuntisDienstOptionen } from "../../api/hooks/useWebuntisDienstOptionen";
import { ApiError } from "../../api/client";
import type { KlassendienstTyp } from "../../api/types";
import styles from "../../components/StudentDetail/StudentDetail.module.css";
import { kuerzelVorschlag, MAX_BESCHREIBUNG, validateKlassendienstTypen } from "./klassendienstValidation";
import type { KlassendienstDraft, KlassendienstValidationError } from "./klassendienstValidation";

function toDraft(typ: KlassendienstTyp): KlassendienstDraft {
  return {
    id: typ.id ?? null,
    webuntis_dienst_id: typ.webuntis_dienst_id,
    bezeichnung: typ.bezeichnung,
    kuerzel: typ.kuerzel,
    beschreibung: typ.beschreibung ?? "",
    aktiv: typ.aktiv,
  };
}

function toPayload(draft: KlassendienstDraft): KlassendienstTyp {
  const beschreibung = draft.beschreibung.trim();
  return {
    ...(draft.id != null ? { id: draft.id } : {}),
    webuntis_dienst_id: draft.webuntis_dienst_id as number,
    bezeichnung: draft.bezeichnung.trim(),
    kuerzel: draft.kuerzel.trim(),
    beschreibung: beschreibung === "" ? null : beschreibung,
    aktiv: draft.aktiv,
  };
}

function speicherFehlerText(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 409 || error.status === 422) {
      return `Speichern abgelehnt: ${error.detail ?? "Die Eingaben sind ungültig bzw. die Dienst-ID ist bereits vergeben."}`;
    }
  }
  return "Fehler beim Speichern der Klassendienste.";
}

export function KlassendienstTypen() {
  const { data, isLoading, isError } = useKlassendienstTypen();
  const optionenQuery = useWebuntisDienstOptionen();
  const { mutate, isPending, error, isSuccess } = useUpdateKlassendienstTypen();
  const [rows, setRows] = useState<KlassendienstDraft[]>([]);
  const [fehler, setFehler] = useState<KlassendienstValidationError[]>([]);
  const [entfernenIndex, setEntfernenIndex] = useState<number | null>(null);

  useEffect(() => {
    if (data) {
      setRows(data.map(toDraft));
    }
  }, [data]);

  if (isLoading) {
    return <p>Lädt…</p>;
  }
  if (isError || !data) {
    return <p>Fehler beim Laden der Klassendienste.</p>;
  }

  const optionen = optionenQuery.data?.optionen ?? [];
  const belegteIds = new Set(rows.map((row) => row.webuntis_dienst_id));
  const freieOptionen = optionen.filter((option) => !belegteIds.has(option.id));
  const optionenHinweis = optionenQuery.isError
    ? "Die Vorschlagsliste aus WebUntis konnte nicht geladen werden. Dienste lassen sich von Hand eintragen."
    : optionen.length === 0 && !optionenQuery.isLoading
      ? (optionenQuery.data?.hinweis ?? "WebUntis hat keine Vorschlagsliste geliefert. Dienste lassen sich von Hand eintragen.")
      : null;

  function updateRow(index: number, patch: Partial<KlassendienstDraft>) {
    setRows((current) => current.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  }

  function addManual() {
    setRows((current) => [
      ...current,
      { id: null, webuntis_dienst_id: null, bezeichnung: "", kuerzel: "", beschreibung: "", aktiv: true },
    ]);
  }

  function addFromOption(idText: string) {
    const option = optionen.find((candidate) => String(candidate.id) === idText);
    if (!option) return;
    setRows((current) => [
      ...current,
      {
        id: null,
        webuntis_dienst_id: option.id,
        bezeichnung: option.bezeichnung,
        kuerzel: kuerzelVorschlag(option.bezeichnung),
        beschreibung: "",
        aktiv: true,
      },
    ]);
  }

  function requestRemove(index: number) {
    if (rows[index].id == null) {
      setRows((current) => current.filter((_, i) => i !== index));
      setFehler([]);
    } else {
      setEntfernenIndex(index);
    }
  }

  function confirmRemove() {
    if (entfernenIndex === null) return;
    setRows((current) => current.filter((_, i) => i !== entfernenIndex));
    setEntfernenIndex(null);
    setFehler([]);
  }

  function save() {
    const errors = validateKlassendienstTypen(rows);
    setFehler(errors);
    if (errors.length > 0) return;
    mutate(rows.map(toPayload));
  }

  function fehlerFuer(index: number, feld: KlassendienstValidationError["feld"]) {
    return fehler.find((candidate) => candidate.rowIndex === index && candidate.feld === feld)?.message;
  }

  function meldung(index: number, feld: KlassendienstValidationError["feld"]) {
    const text = fehlerFuer(index, feld);
    return text ? (
      <div role="alert" className={styles.formError}>
        {text}
      </div>
    ) : null;
  }
  return (
    <section className={styles.section}>
      <h3>Klassendienste</h3>
      <p>
        Hier legt die Schulleitung fest, welche WebUntis-Klassendienste (z. B. Entschuldigungspflicht, Attestpflicht) in
        AbsenzDash angezeigt werden. Die Dienst-IDs stammen aus den WebUntis-Stammdaten der Schule. Der Import läuft
        höchstens einmal täglich. Die Dienste werden nur angezeigt und haben keinen Einfluss auf Zähler, Eskalation oder
        Benachrichtigungen. Das Kürzel erscheint als Badge in der Schülerliste, die Erklärung als Hover-Text.
      </p>
      <table className={styles.table}>
        <thead>
          <tr>
            <th>Dienst-ID</th>
            <th>Bezeichnung</th>
            <th>Kürzel</th>
            <th>Erklärung (Hover-Text)</th>
            <th>Aktiv</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={row.id ?? `neu-${index}`}>
              <td>
                <input
                  aria-label={`Dienst-ID Zeile ${index + 1}`}
                  type="number"
                  min={1}
                  step={1}
                  value={row.webuntis_dienst_id ?? ""}
                  onChange={(event) =>
                    updateRow(index, {
                      webuntis_dienst_id: event.target.value === "" ? null : Number(event.target.value),
                    })
                  }
                />
                {meldung(index, "webuntis_dienst_id")}
              </td>
              <td>
                <input
                  aria-label={`Bezeichnung Zeile ${index + 1}`}
                  type="text"
                  value={row.bezeichnung}
                  onChange={(event) => updateRow(index, { bezeichnung: event.target.value })}
                />
                {meldung(index, "bezeichnung")}
              </td>
              <td>
                <input
                  aria-label={`Kürzel Zeile ${index + 1}`}
                  type="text"
                  size={5}
                  value={row.kuerzel}
                  onChange={(event) => updateRow(index, { kuerzel: event.target.value })}
                />
                {meldung(index, "kuerzel")}
              </td>
              <td>
                <input
                  aria-label={`Erklärung Zeile ${index + 1}`}
                  type="text"
                  value={row.beschreibung}
                  placeholder={`optional, höchstens ${MAX_BESCHREIBUNG} Zeichen`}
                  onChange={(event) => updateRow(index, { beschreibung: event.target.value })}
                />
                {meldung(index, "beschreibung")}
              </td>
              <td>
                <input
                  aria-label={`Aktiv Zeile ${index + 1}`}
                  type="checkbox"
                  checked={row.aktiv}
                  onChange={(event) => updateRow(index, { aktiv: event.target.checked })}
                />
              </td>
              <td>
                <button type="button" onClick={() => requestRemove(index)}>
                  Entfernen
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {entfernenIndex !== null && (
        <div role="alertdialog" aria-label="Entfernen bestätigen" className={styles.formError}>
          <p>
            Beim Speichern wird „{rows[entfernenIndex]?.bezeichnung}“ samt aller importierten Schüler-Zuordnungen
            gelöscht. Alternative: den Dienst nur deaktivieren (Haken bei „Aktiv“ entfernen), dann bleibt er erhalten, wird
            aber nicht mehr angezeigt.
          </p>
          <button type="button" onClick={confirmRemove}>
            Endgültig entfernen
          </button>{" "}
          <button type="button" onClick={() => setEntfernenIndex(null)}>
            Abbrechen
          </button>
        </div>
      )}
      <div>
        <label>
          Dienst aus WebUntis wählen{" "}
          <select
            aria-label="Dienst aus WebUntis"
            value=""
            disabled={freieOptionen.length === 0}
            onChange={(event) => addFromOption(event.target.value)}
          >
            <option value="">– auswählen –</option>
            {freieOptionen.map((option) => (
              <option key={option.id} value={option.id}>
                {option.id}: {option.bezeichnung}
              </option>
            ))}
          </select>
        </label>{" "}
        <button type="button" onClick={addManual}>
          Dienst hinzufügen (manuell)
        </button>
      </div>
      {optionenHinweis && <p>{optionenHinweis}</p>}
      <button type="button" onClick={save} disabled={isPending}>
        Speichern
      </button>
      {fehler.length > 0 && <p className={styles.formError}>Bitte die markierten Eingaben korrigieren.</p>}
      {error && <p className={styles.formError}>{speicherFehlerText(error)}</p>}
      {isSuccess && !error && <p>Gespeichert.</p>}
    </section>
  );
}
