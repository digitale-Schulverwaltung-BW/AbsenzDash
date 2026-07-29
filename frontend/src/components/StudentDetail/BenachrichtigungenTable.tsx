import type { Benachrichtigung } from "../../api/types";
import styles from "./StudentDetail.module.css";

interface BenachrichtigungenTableProps {
  benachrichtigungen: Benachrichtigung[];
}

const STATUS_TEXT: Record<string, string> = {
  kein_empfaenger: "Kein Empfänger ermittelbar",
  initial_import: "Aus initialem Datenimport übernommen",
};

export function BenachrichtigungenTable({ benachrichtigungen }: BenachrichtigungenTableProps) {
  return (
    <table className={styles.table}>
      <thead>
        <tr>
          <th>Zeitpunkt</th>
          <th>Regel</th>
          <th>Stufe</th>
          <th>Empfänger</th>
        </tr>
      </thead>
      <tbody>
        {benachrichtigungen.map((benachrichtigung) => (
          <tr key={benachrichtigung.id}>
            <td>{benachrichtigung.gesendet_am}</td>
            <td>{benachrichtigung.typ ?? "—"}</td>
            <td>{benachrichtigung.stufe_nr}</td>
            <td>
              {benachrichtigung.empfaenger.length > 0 ? (
                <ul>
                  {benachrichtigung.empfaenger.map((empfaenger, index) => (
                    <li key={index}>
                      {empfaenger.name ? `${empfaenger.rolle}: ${empfaenger.name}` : empfaenger.rolle}
                    </li>
                  ))}
                </ul>
              ) : (
                STATUS_TEXT[benachrichtigung.status] ?? benachrichtigung.status
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
