import type { ExcuseStatusCatalogEntry, Fehlzeit } from "../../api/types";
import styles from "./StudentDetail.module.css";

interface FehlzeitenTableProps {
  fehlzeiten: Fehlzeit[];
  excuseStatuses: ExcuseStatusCatalogEntry[];
}

export function FehlzeitenTable({ fehlzeiten, excuseStatuses }: FehlzeitenTableProps) {
  const statusMap = new Map(excuseStatuses.map((status) => [status.id, status.long_name ?? status.name]));

  return (
    <table className={styles.table}>
      <thead>
        <tr>
          <th>Datum</th>
          <th>Typ</th>
          <th>Zeit</th>
          <th>Fach</th>
          <th>Entschuldigungsstatus</th>
          <th>Grund</th>
        </tr>
      </thead>
      <tbody>
        {fehlzeiten.map((fehlzeit) => (
          <tr key={fehlzeit.id}>
            <td>{fehlzeit.datum}</td>
            <td>{fehlzeit.typ}</td>
            <td>
              {fehlzeit.typ === "tag" ? "ganztägig" : `${fehlzeit.start_zeit}–${fehlzeit.end_zeit}`}
            </td>
            <td>{fehlzeit.fach ?? "—"}</td>
            <td>{fehlzeit.excuse_status_id !== null ? statusMap.get(fehlzeit.excuse_status_id) ?? "—" : "—"}</td>
            <td>{fehlzeit.grund_text ?? "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
