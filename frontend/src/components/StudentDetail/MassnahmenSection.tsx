import { useEffect, useState } from "react";
import { useCreateMeasure } from "../../api/hooks/useCreateMeasure";
import type { Massnahme, MassnahmenTyp } from "../../api/types";
import styles from "./StudentDetail.module.css";

interface MassnahmenSectionProps {
  studentId: number;
  massnahmen: Massnahme[];
  massnahmenTypen: MassnahmenTyp[];
}

export function MassnahmenSection({ studentId, massnahmen, massnahmenTypen }: MassnahmenSectionProps) {
  const { mutate, isPending, isSuccess, error } = useCreateMeasure(studentId);
  const [typId, setTypId] = useState(massnahmenTypen[0]?.id ?? 0);
  const [datum, setDatum] = useState("");
  const [notiz, setNotiz] = useState("");

  useEffect(() => {
    if (isSuccess) {
      setDatum("");
      setNotiz("");
    }
  }, [isSuccess]);

  // massnahmenTypen may still be empty at mount if useStudentCatalog resolves after
  // useStudentDetail (StudentDetail.tsx fires both in parallel and only gates rendering on the
  // detail query). The useState initializer above only runs once, so once the catalog arrives we
  // need to sync typId to the first available type — but only while the user hasn't made a valid
  // selection yet, so we don't override an in-progress choice.
  useEffect(() => {
    if (typId === 0 && massnahmenTypen.length > 0) {
      setTypId(massnahmenTypen[0].id);
    }
  }, [massnahmenTypen, typId]);

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    mutate({ massnahmen_typ_id: typId, datum, notiz: notiz || null });
  }

  return (
    <section className={styles.section}>
      <h3>Maßnahmen</h3>
      <table className={styles.table}>
        <thead>
          <tr>
            <th>Datum</th>
            <th>Typ</th>
            <th>Notiz</th>
            <th>Erfasst von</th>
          </tr>
        </thead>
        <tbody>
          {massnahmen.map((massnahme) => (
            <tr key={massnahme.id}>
              <td>{massnahme.datum}</td>
              <td>{massnahme.massnahmen_typ_name}</td>
              <td>{massnahme.notiz ?? "—"}</td>
              <td>{massnahme.erfasst_von_name}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <form className={styles.form} onSubmit={handleSubmit}>
        <label>
          Typ
          <select
            aria-label="Typ"
            value={typId}
            onChange={(event) => setTypId(Number(event.target.value))}
          >
            {massnahmenTypen.map((typ) => (
              <option key={typ.id} value={typ.id}>
                {typ.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Datum
          <input aria-label="Datum" type="date" value={datum} onChange={(event) => setDatum(event.target.value)} required />
        </label>
        <label>
          Notiz
          <textarea aria-label="Notiz" value={notiz} onChange={(event) => setNotiz(event.target.value)} />
        </label>
        <button type="submit" disabled={isPending}>
          Maßnahme erfassen
        </button>
        {error && <p className={styles.formError}>Fehler beim Erfassen der Maßnahme.</p>}
      </form>
    </section>
  );
}
