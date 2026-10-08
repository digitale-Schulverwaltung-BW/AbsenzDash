import type { Klassendienst } from "../../api/types";
import { formatDatumDe, heuteIso } from "../../utils/datum";
import { klassendienstStatus } from "../../utils/klassendienst";
import styles from "./StudentDetail.module.css";

interface KlassendiensteSectionProps {
  klassendienste: Klassendienst[] | undefined;
  /** "YYYY-MM-DD"; injizierbar für Tests, Standard: heute. */
  heute?: string;
}

export function KlassendiensteSection({ klassendienste, heute }: KlassendiensteSectionProps) {
  const eintraege = klassendienste ?? [];
  const stichtag = heute ?? heuteIso();
  return (
    <section className={styles.section}>
      <h3>Klassendienste (aus WebUntis, schreibgeschützt)</h3>
      {eintraege.length === 0 ? (
        <p>Keine Klassendienste hinterlegt.</p>
      ) : (
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Dienst</th>
              <th>Zeitraum</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {eintraege.map((dienst) => (
              <tr key={`${dienst.typ_id}-${dienst.von}`}>
                <td title={dienst.beschreibung ?? undefined}>
                  <strong>{dienst.kuerzel}</strong> {dienst.bezeichnung}
                  {dienst.beschreibung ? <div className={styles.metricSplit}>{dienst.beschreibung}</div> : null}
                </td>
                <td>
                  {formatDatumDe(dienst.von)} – {formatDatumDe(dienst.bis)}
                </td>
                <td>{klassendienstStatus(dienst, stichtag)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
