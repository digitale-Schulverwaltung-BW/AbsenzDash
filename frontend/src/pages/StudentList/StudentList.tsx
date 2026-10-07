import { Link, useSearchParams } from "react-router-dom";
import type { StudentSortField } from "../../api/hooks/useStudents";
import { useStudents } from "../../api/hooks/useStudents";
import type { FehlzeitSplit, StudentOverview, TrendRichtung, TrendWert } from "../../api/types";
import { EskalationsBadge } from "../../components/EskalationsBadge/EskalationsBadge";
import { NotificationFlyout } from "../../components/NotificationFlyout/NotificationFlyout";
import { anonymisiereName, istAnonymisierungAktiv, istAnonymisierungErlaubt } from "../../utils/anonymize";
import { valueToColor } from "../../utils/colorScale";
import { parseTrendTage, TREND_TAGE_OPTIONEN } from "../../utils/trend";
import type { TrendTage } from "../../utils/trend";
import styles from "./StudentList.module.css";

interface SpalteConfig {
  feld: StudentSortField;
  label: string;
}

const SORTIERBARE_SPALTEN: SpalteConfig[] = [
  { feld: "nachname", label: "Name" },
  { feld: "klasse", label: "Klasse" },
  { feld: "fehltage", label: "Fehltage" },
  { feld: "fehlstunden", label: "Fehlstunden" },
  { feld: "klassenbuch_anzahl", label: "Einträge" },
];

function splitTitle(split: FehlzeitSplit): string {
  return `${split.entschuldigt} entschuldigt, ${split.unentschuldigt} unentschuldigt`;
}

const TREND_DARSTELLUNG: Record<TrendRichtung, { pfeil: string; label: string; klasse: string }> = {
  steigend: { pfeil: "↗", label: "steigend", klasse: styles.trendSteigend },
  gleich: { pfeil: "→", label: "gleich", klasse: styles.trendGleich },
  fallend: { pfeil: "↘", label: "fallend", klasse: styles.trendFallend },
};

function TrendPfeil({ trend, tage }: { trend: TrendWert | null | undefined; tage: TrendTage | null }) {
  if (!trend || trend.richtung === null || tage === null) return null;
  const darstellung = TREND_DARSTELLUNG[trend.richtung];
  const text = `Letzte ${tage} Tage: ${trend.aktuell}, davor: ${trend.vorher}`;
  return (
    <span
      role="img"
      aria-label={`Trend ${darstellung.label}. ${text}`}
      title={text}
      data-richtung={trend.richtung}
      className={`${styles.trend} ${darstellung.klasse}`}
    >
      {darstellung.pfeil}
    </span>
  );
}

function extremwerte(items: StudentOverview[], feld: "fehltage" | "fehlstunden"): [number, number] {
  const werte = items.map((item) => item[feld]?.gesamt ?? 0);
  if (werte.length === 0) return [0, 0];
  return [Math.min(...werte), Math.max(...werte)];
}

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
  const sortByParam = searchParams.get("sort_by") as StudentSortField | null;
  const sortDirParam = searchParams.get("sort_dir") === "desc" ? "desc" : "asc";
  const trendTage = isHistoryMode ? null : parseTrendTage(searchParams.get("trend_tage"));
  const anonymisierungErlaubt = istAnonymisierungErlaubt();
  const anonymisieren = anonymisierungErlaubt && istAnonymisierungAktiv(searchParams);

  const { data, isLoading, isError } = useStudents({
    bereichId: bereichParam ? Number(bereichParam) : null,
    klasseId: klasseParam ? Number(klasseParam) : null,
    minStufe: minStufeParam ? Number(minStufeParam) : null,
    nurAuffaellige,
    offset,
    schuljahrId,
    sortBy: sortByParam,
    sortDir: sortDirParam,
    trendTage,
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

  function handleSort(feld: StudentSortField) {
    const next = new URLSearchParams(searchParams);
    if (sortByParam === feld) {
      next.set("sort_dir", sortDirParam === "asc" ? "desc" : "asc");
    } else {
      next.set("sort_by", feld);
      next.set("sort_dir", "asc");
    }
    next.delete("offset");
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

  const [fehltageMin, fehltageMax] = extremwerte(data.items, "fehltage");
  const [fehlstundenMin, fehlstundenMax] = extremwerte(data.items, "fehlstunden");
  const maxStufeNr = Math.max(
    1,
    ...data.items.flatMap((item) =>
      Object.values(item.zaehlerstand ?? {}).map((stand) => stand.erreichte_stufe_nr ?? 0),
    ),
  );

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
        {isHistoryMode ? null : (
          <label>
            Trend-Zeitraum{" "}
            <select value={trendTage ?? ""} onChange={(event) => updateParam("trend_tage", event.target.value)}>
              <option value="">Aus</option>
              {TREND_TAGE_OPTIONEN.map((tage) => (
                <option key={tage} value={tage}>
                  {tage} Tage
                </option>
              ))}
            </select>
          </label>
        )}
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
            {SORTIERBARE_SPALTEN.map((spalte) => (
              <th key={spalte.feld} onClick={() => handleSort(spalte.feld)}>
                <button type="button" className={styles.sortButton}>
                  {spalte.label}
                  {sortByParam === spalte.feld ? (sortDirParam === "asc" ? " ▲" : " ▼") : ""}
                </button>
              </th>
            ))}
            {isHistoryMode ? null : (
              <>
                <th>Eskalationsstufe</th>
                <th>Benachrichtigt</th>
              </>
            )}
          </tr>
        </thead>
        <tbody>
          {data.items.map((student) => {
            const name = anonymisieren ? anonymisiereName(student.id) : student;
            return (
              <tr
                key={student.id}
                data-highlighted={student.ohne_massnahme_seit_benachrichtigung}
                className={student.ohne_massnahme_seit_benachrichtigung ? styles.highlighted : undefined}
              >
                <td>
                  <Link to={`/schueler/${student.id}${anonymisieren ? "?a=1" : ""}`}>
                    {name.nachname}, {name.vorname}
                  </Link>
                </td>
                <td>{student.klasse?.name ?? "—"}</td>
                <td
                  title={student.fehltage ? splitTitle(student.fehltage) : undefined}
                  style={{
                    color: student.fehltage ? valueToColor(student.fehltage.gesamt, fehltageMin, fehltageMax) : undefined,
                  }}
                >
                  {student.fehltage?.gesamt ?? "—"}
                  <TrendPfeil trend={student.trend?.fehltage} tage={trendTage} />
                </td>
                <td
                  title={student.fehlstunden ? splitTitle(student.fehlstunden) : undefined}
                  style={{
                    color: student.fehlstunden
                      ? valueToColor(student.fehlstunden.gesamt, fehlstundenMin, fehlstundenMax)
                      : undefined,
                  }}
                >
                  {student.fehlstunden?.gesamt ?? "—"}
                  <TrendPfeil trend={student.trend?.fehlstunden} tage={trendTage} />
                </td>
                <td>{student.klassenbuch_anzahl ?? "—"}</td>
                {isHistoryMode ? null : (
                  <>
                    <td>
                      <div className={styles.badges}>
                        {Object.entries(student.zaehlerstand ?? {}).map(([typ, stand]) => (
                          <EskalationsBadge key={typ} stufeNr={stand.erreichte_stufe_nr} maxStufeNr={maxStufeNr} />
                        ))}
                      </div>
                    </td>
                    <td>
                      <NotificationFlyout benachrichtigung={student.letzte_benachrichtigung} />
                    </td>
                  </>
                )}
              </tr>
            );
          })}
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
        {anonymisierungErlaubt ? (
          <label className={styles.anonymisierenToggle}>
            <input
              type="checkbox"
              aria-label="Anonymisieren"
              checked={anonymisieren}
              onChange={(event) => updateParam("a", event.target.checked ? "1" : "")}
            />{" "}
            Anonymisieren
          </label>
        ) : null}
      </div>
    </div>
  );
}
