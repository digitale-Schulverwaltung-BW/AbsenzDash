import { Link, useSearchParams } from "react-router-dom";
import { useStudents } from "../../api/hooks/useStudents";
import { NotificationFlyout } from "../../components/NotificationFlyout/NotificationFlyout";
import { StatusBadge, stufeToTone } from "../../components/StatusBadge/StatusBadge";
import styles from "./StudentList.module.css";

const ZAEHLERSTAND_LABEL: Record<string, string> = {
  fehlzeiten: "Fehlzeiten",
  klassenbuch: "Klassenbuch",
};

export function StudentList() {
  const [searchParams, setSearchParams] = useSearchParams();

  const bereichParam = searchParams.get("bereich");
  const klasseParam = searchParams.get("klasse");
  const minStufeParam = searchParams.get("min_stufe");
  const nurAuffaellige = searchParams.get("nur_auffaellige") === "true";
  const offset = Number(searchParams.get("offset") ?? "0");
  const schuljahrParam = searchParams.get("schuljahr");
  const schuljahrId = schuljahrParam ? Number(schuljahrParam) : null;
  const isHistoryMode = schuljahrId !== null;

  const { data, isLoading, isError } = useStudents({
    bereichId: bereichParam ? Number(bereichParam) : null,
    klasseId: klasseParam ? Number(klasseParam) : null,
    minStufe: minStufeParam ? Number(minStufeParam) : null,
    nurAuffaellige,
    offset,
    schuljahrId,
  });

  function updateParam(name: string, value: string) {
    const next = new URLSearchParams(searchParams);
    if (value === "") {
      next.delete(name);
    } else {
      next.set(name, value);
    }
    next.delete("offset");
    setSearchParams(next);
  }

  function goToOffset(newOffset: number) {
    const next = new URLSearchParams(searchParams);
    next.set("offset", String(newOffset));
    setSearchParams(next);
  }

  if (isLoading) {
    return <p>Lädt Schülerliste…</p>;
  }
  if (isError || !data) {
    return <p>Fehler beim Laden der Schülerliste.</p>;
  }

  const hasPrevious = offset > 0;
  const hasNext = offset + data.limit < data.total;
  const rangeStart = data.total === 0 ? 0 : offset + 1;
  const rangeEnd = Math.min(offset + data.limit, data.total);

  return (
    <div>
      <div className={styles.filters}>
        <label>
          Mindeststufe{" "}
          <select value={minStufeParam ?? ""} onChange={(event) => updateParam("min_stufe", event.target.value)}>
            <option value="">Alle</option>
            <option value="1">1</option>
            <option value="2">2</option>
            <option value="3">3</option>
          </select>
        </label>
        <label>
          <input
            type="checkbox"
            aria-label="Nur auffällige"
            checked={nurAuffaellige}
            onChange={(event) => updateParam("nur_auffaellige", event.target.checked ? "true" : "")}
          />{" "}
          Nur auffällige
        </label>
      </div>
      <table className={styles.table}>
        <thead>
          <tr>
            <th>Name</th>
            <th>Klasse</th>
            {isHistoryMode ? (
              <>
                <th>Fehltage</th>
                <th>Fehlstunden</th>
                <th>Klassenbuch</th>
              </>
            ) : (
              <>
                <th>Zählerstand</th>
                <th>Benachrichtigt</th>
              </>
            )}
          </tr>
        </thead>
        <tbody>
          {data.items.map((student) => (
            <tr
              key={student.id}
              data-highlighted={student.ohne_massnahme_seit_benachrichtigung}
              className={student.ohne_massnahme_seit_benachrichtigung ? styles.highlighted : undefined}
            >
              <td>
                <Link to={`/schueler/${student.id}`}>
                  {student.nachname}, {student.vorname}
                </Link>
              </td>
              <td>{student.klasse?.name ?? "—"}</td>
              {isHistoryMode ? (
                <>
                  <td>{student.fehltage}</td>
                  <td>{student.fehlstunden}</td>
                  <td>{student.klassenbuch_anzahl}</td>
                </>
              ) : (
                <>
                  <td>
                    <div className={styles.badges}>
                      {Object.entries(student.zaehlerstand ?? {}).map(([typ, stand]) => (
                        <StatusBadge
                          key={typ}
                          label={`${ZAEHLERSTAND_LABEL[typ] ?? typ}: ${stand.erreichte_stufe_nr ?? "–"}`}
                          tone={stufeToTone(stand.erreichte_stufe_nr)}
                        />
                      ))}
                    </div>
                  </td>
                  <td>
                    <NotificationFlyout benachrichtigung={student.letzte_benachrichtigung} />
                  </td>
                </>
              )}
            </tr>
          ))}
        </tbody>
      </table>
      <div className={styles.pagination}>
        <button type="button" disabled={!hasPrevious} onClick={() => goToOffset(Math.max(0, offset - data.limit))}>
          Zurück
        </button>
        <span>
          {rangeStart}–{rangeEnd} von {data.total}
        </span>
        <button type="button" disabled={!hasNext} onClick={() => goToOffset(offset + data.limit)}>
          Weiter
        </button>
      </div>
    </div>
  );
}
