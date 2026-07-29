import type { ClassregCategoryCatalogEntry, KlassenbuchEintrag } from "../../api/types";
import styles from "./StudentDetail.module.css";

interface KlassenbuchTableProps {
  eintraege: KlassenbuchEintrag[];
  classregCategories: ClassregCategoryCatalogEntry[];
}

export function KlassenbuchTable({ eintraege, classregCategories }: KlassenbuchTableProps) {
  const kategorieMap = new Map(
    classregCategories.map((kategorie) => [kategorie.id, kategorie.long_name ?? kategorie.name]),
  );

  return (
    <table className={styles.table}>
      <thead>
        <tr>
          <th>Datum</th>
          <th>Kategorie</th>
          <th>Text</th>
        </tr>
      </thead>
      <tbody>
        {eintraege.map((eintrag) => (
          <tr key={eintrag.id}>
            <td>{eintrag.datum}</td>
            <td>{kategorieMap.get(eintrag.kategorie_id) ?? "—"}</td>
            <td>{eintrag.text ?? "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
