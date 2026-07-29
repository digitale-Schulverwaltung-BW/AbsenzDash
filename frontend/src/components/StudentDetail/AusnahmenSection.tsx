import { useEffect, useState } from "react";
import { useCreateExemption } from "../../api/hooks/useCreateExemption";
import { useRevokeExemption } from "../../api/hooks/useRevokeExemption";
import type { Ausnahme } from "../../api/types";
import styles from "./StudentDetail.module.css";

interface AusnahmenSectionProps {
  studentId: number;
  ausnahmen: Ausnahme[];
}

export function AusnahmenSection({ studentId, ausnahmen }: AusnahmenSectionProps) {
  const { mutate: createMutate, isPending: isCreating, isSuccess, error } = useCreateExemption(studentId);
  const { mutate: revokeMutate } = useRevokeExemption(studentId);
  const [kategorie, setKategorie] = useState<"fehlzeiten" | "klassenbuch">("fehlzeiten");
  const [grund, setGrund] = useState("");
  const [gueltigBis, setGueltigBis] = useState("");

  useEffect(() => {
    if (isSuccess) {
      setGrund("");
      setGueltigBis("");
    }
  }, [isSuccess]);

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    createMutate({ kategorie, grund, gueltig_bis: gueltigBis || null });
  }

  return (
    <section className={styles.section}>
      <h3>Ausnahmen</h3>
      <table className={styles.table}>
        <thead>
          <tr>
            <th>Kategorie</th>
            <th>Grund</th>
            <th>Gültig bis</th>
            <th>Status</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {ausnahmen.map((ausnahme) => (
            <tr key={ausnahme.id}>
              <td>{ausnahme.kategorie}</td>
              <td>{ausnahme.grund}</td>
              <td>{ausnahme.gueltig_bis ?? "unbefristet"}</td>
              <td>{ausnahme.aktiv ? "aktiv" : "aufgehoben"}</td>
              <td>
                {ausnahme.aktiv && (
                  <button type="button" onClick={() => revokeMutate(ausnahme.id)}>
                    Aufheben
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <form className={styles.form} onSubmit={handleSubmit}>
        <label>
          <input
            type="radio"
            name="kategorie"
            value="fehlzeiten"
            checked={kategorie === "fehlzeiten"}
            onChange={() => setKategorie("fehlzeiten")}
          />{" "}
          Fehlzeiten
        </label>
        <label>
          <input
            type="radio"
            name="kategorie"
            value="klassenbuch"
            checked={kategorie === "klassenbuch"}
            onChange={() => setKategorie("klassenbuch")}
          />{" "}
          Klassenbuch
        </label>
        <label>
          Grund
          <input aria-label="Grund" type="text" value={grund} onChange={(event) => setGrund(event.target.value)} required />
        </label>
        <label>
          Gültig bis
          <input
            aria-label="Gültig bis"
            type="date"
            value={gueltigBis}
            onChange={(event) => setGueltigBis(event.target.value)}
          />
        </label>
        <button type="submit" disabled={isCreating}>
          Ausnahme setzen
        </button>
        {error && <p className={styles.formError}>Fehler beim Setzen der Ausnahme.</p>}
      </form>
    </section>
  );
}
