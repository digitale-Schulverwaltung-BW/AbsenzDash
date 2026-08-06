import { useParams, useSearchParams } from "react-router-dom";
import { useStudentCatalog } from "../../api/hooks/useStudentCatalog";
import { useStudentDetail } from "../../api/hooks/useStudentDetail";
import { AusnahmenSection } from "../../components/StudentDetail/AusnahmenSection";
import { BenachrichtigungenTable } from "../../components/StudentDetail/BenachrichtigungenTable";
import { FehlzeitenTable } from "../../components/StudentDetail/FehlzeitenTable";
import { KlassenbuchTable } from "../../components/StudentDetail/KlassenbuchTable";
import { MassnahmenSection } from "../../components/StudentDetail/MassnahmenSection";
import { PdfExportSection } from "../../components/StudentDetail/PdfExportSection";
import styles from "../../components/StudentDetail/StudentDetail.module.css";
import { StatusBadge, stufeToTone } from "../../components/StatusBadge/StatusBadge";
import { anonymisiereName, istAnonymisierungAktiv } from "../../utils/anonymize";

const ZAEHLERSTAND_LABEL: Record<string, string> = {
  fehlzeiten: "Fehlzeiten",
  klassenbuch: "Klassenbuch",
};

export function StudentDetail() {
  const { id } = useParams<{ id: string }>();
  const studentId = Number(id);
  const [searchParams] = useSearchParams();
  const schuljahrParam = searchParams.get("schuljahr");
  const schuljahrId = schuljahrParam ? Number(schuljahrParam) : null;
  const { data: student, isLoading, isError } = useStudentDetail(studentId, schuljahrId);
  const { data: catalog } = useStudentCatalog();

  if (isLoading) {
    return <p>Lädt Schülerdaten…</p>;
  }
  if (isError || !student) {
    return <p>Fehler beim Laden des Schülers.</p>;
  }

  const anonymisieren = istAnonymisierungAktiv(searchParams);
  const name = anonymisieren ? anonymisiereName(student.id) : student;

  return (
    <div>
      <section className={styles.section}>
        <h2>
          {name.nachname}, {name.vorname}
        </h2>
        <p>{student.klasse?.name ?? "—"}</p>
        <div className={styles.metrics}>
          <div className={styles.metric}>
            <span className={styles.metricLabel}>Fehltage</span>
            <span className={styles.metricValue}>{student.fehltage.gesamt}</span>
            <span className={styles.metricSplit}>
              {student.fehltage.entschuldigt} entschuldigt, {student.fehltage.unentschuldigt} unentschuldigt
            </span>
          </div>
          <div className={styles.metric}>
            <span className={styles.metricLabel}>Fehlstunden</span>
            <span className={styles.metricValue}>{student.fehlstunden.gesamt}</span>
            <span className={styles.metricSplit}>
              {student.fehlstunden.entschuldigt} entschuldigt, {student.fehlstunden.unentschuldigt} unentschuldigt
            </span>
          </div>
          <div className={styles.metric}>
            <span className={styles.metricLabel}>Klassenbuch-Einträge</span>
            <span className={styles.metricValue}>{student.klassenbuch_anzahl}</span>
          </div>
        </div>
        <div>
          <span className={styles.metricLabel}>Eskalations-Stufen: </span>
          {Object.entries(student.zaehlerstand).map(([typ, stand]) => (
            <StatusBadge
              key={typ}
              label={`${ZAEHLERSTAND_LABEL[typ] ?? typ}: ${stand.erreichte_stufe_nr ?? "–"}`}
              tone={stufeToTone(stand.erreichte_stufe_nr)}
            />
          ))}
        </div>
      </section>
      <section className={styles.section}>
        <h3>Fehlzeiten</h3>
        <FehlzeitenTable fehlzeiten={student.fehlzeiten} excuseStatuses={catalog?.excuse_statuses ?? []} />
      </section>
      <section className={styles.section}>
        <h3>Klassenbuch</h3>
        <KlassenbuchTable eintraege={student.klassenbuch} classregCategories={catalog?.classreg_categories ?? []} />
      </section>
      <MassnahmenSection
        studentId={studentId}
        massnahmen={student.massnahmen}
        massnahmenTypen={catalog?.massnahmen_typen ?? []}
      />
      <AusnahmenSection studentId={studentId} ausnahmen={student.ausnahmen} />
      <section className={styles.section}>
        <h3>Benachrichtigungen</h3>
        <BenachrichtigungenTable benachrichtigungen={student.benachrichtigungen} />
      </section>
      <PdfExportSection studentId={studentId} schuljahrId={schuljahrId} />
    </div>
  );
}
