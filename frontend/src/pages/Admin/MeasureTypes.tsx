import { useEffect, useState } from "react";
import { useMeasureTypes } from "../../api/hooks/useMeasureTypes";
import { useUpdateMeasureTypes } from "../../api/hooks/useUpdateMeasureTypes";
import type { MeasureType } from "../../api/types";
import styles from "../../components/StudentDetail/StudentDetail.module.css";

export function MeasureTypes() {
  const { data, isLoading, isError } = useMeasureTypes();
  const { mutate, isPending, error } = useUpdateMeasureTypes();
  const [rows, setRows] = useState<MeasureType[]>([]);

  useEffect(() => {
    if (data) {
      setRows(data);
    }
  }, [data]);

  if (isLoading) {
    return <p>Lädt…</p>;
  }
  if (isError || !data) {
    return <p>Fehler beim Laden des Maßnahmen-Katalogs.</p>;
  }

  function updateRow(index: number, patch: Partial<MeasureType>) {
    setRows((current) => current.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  }

  function removeRow(index: number) {
    setRows((current) => current.filter((_, i) => i !== index));
  }

  function addRow() {
    setRows((current) => [...current, { name: "", setzt_zaehler_zurueck: false, aktiv: true }]);
  }

  return (
    <section className={styles.section}>
      <h3>Maßnahmen-Katalog</h3>
      <table className={styles.table}>
        <thead>
          <tr>
            <th>Name</th>
            <th>Setzt Zähler zurück</th>
            <th>Aktiv</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={row.id ?? `neu-${index}`}>
              <td>
                <input
                  aria-label={`Name Zeile ${index + 1}`}
                  type="text"
                  value={row.name}
                  onChange={(event) => updateRow(index, { name: event.target.value })}
                />
              </td>
              <td>
                <input
                  aria-label={`Setzt Zähler zurück Zeile ${index + 1}`}
                  type="checkbox"
                  checked={row.setzt_zaehler_zurueck}
                  onChange={(event) => updateRow(index, { setzt_zaehler_zurueck: event.target.checked })}
                />
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
                <button type="button" onClick={() => removeRow(index)}>
                  Entfernen
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <button type="button" onClick={addRow}>
        Neuer Maßnahmen-Typ
      </button>
      <button type="button" onClick={() => mutate(rows)} disabled={isPending}>
        Speichern
      </button>
      {error && <p className={styles.formError}>Fehler beim Speichern — z.B. Name bereits vergeben.</p>}
    </section>
  );
}
