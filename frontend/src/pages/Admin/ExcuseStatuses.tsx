import { useEffect, useState } from "react";
import { useExcuseStatuses } from "../../api/hooks/useExcuseStatuses";
import { useUpdateExcuseStatuses } from "../../api/hooks/useUpdateExcuseStatuses";
import type { ExcuseStatus } from "../../api/types";
import styles from "../../components/StudentDetail/StudentDetail.module.css";

export function ExcuseStatuses() {
  const { data, isLoading, isError } = useExcuseStatuses();
  const { mutate, isPending, error } = useUpdateExcuseStatuses();
  const [rows, setRows] = useState<ExcuseStatus[]>([]);

  useEffect(() => {
    if (data) {
      setRows(data);
    }
  }, [data]);

  if (isLoading) {
    return <p>Lädt…</p>;
  }
  if (isError || !data) {
    return <p>Fehler beim Laden der Entschuldigungsstatus.</p>;
  }

  function toggle(id: number) {
    setRows((current) =>
      current.map((row) => (row.id === id ? { ...row, zaehlt_als_entschuldigt: !row.zaehlt_als_entschuldigt } : row)),
    );
  }

  return (
    <section className={styles.section}>
      <h3>Entschuldigungsstatus</h3>
      <p>
        Namen werden automatisch beim WebUntis-Sync übernommen und können hier nicht geändert werden — nur ob ein
        Status als entschuldigt zählt.
      </p>
      <table className={styles.table}>
        <thead>
          <tr>
            <th>Name</th>
            <th>Entschuldigt</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id}>
              <td>{row.name}</td>
              <td>
                <input
                  aria-label={`Entschuldigt: ${row.name}`}
                  type="checkbox"
                  checked={row.zaehlt_als_entschuldigt}
                  onChange={() => toggle(row.id)}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <button type="button" onClick={() => mutate(rows)} disabled={isPending}>
        Speichern
      </button>
      {error && <p className={styles.formError}>Fehler beim Speichern.</p>}
    </section>
  );
}
