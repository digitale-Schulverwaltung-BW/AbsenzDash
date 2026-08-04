import { useState } from "react";
import { apiDownload } from "../../api/client";
import { useNavOptions } from "../../api/hooks/useNavOptions";
import styles from "./StudentDetail.module.css";
import { ALL_SECTIONS, buildSectionsParam } from "./pdfExportSections";

const SECTION_LABELS: Record<(typeof ALL_SECTIONS)[number], string> = {
  fehlzeiten: "Fehlzeiten",
  klassenbuch: "Klassenbuch",
  massnahmen: "Maßnahmen",
  ausnahmen: "Ausnahmen",
  benachrichtigungen: "Benachrichtigungen",
};

interface PdfExportSectionProps {
  studentId: number;
  schuljahrId: number | null;
}

export function PdfExportSection({ studentId, schuljahrId }: PdfExportSectionProps) {
  const { data: navOptions } = useNavOptions();
  const [selected, setSelected] = useState<Set<string>>(new Set(ALL_SECTIONS));
  const [isPending, setIsPending] = useState(false);
  const [attemptedExport, setAttemptedExport] = useState(false);
  const [error, setError] = useState(false);

  const schuljahrName = schuljahrId != null ? navOptions?.schuljahre.find((s) => s.id === schuljahrId)?.name : undefined;

  function toggleSection(section: string) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(section)) {
        next.delete(section);
      } else {
        next.add(section);
      }
      return next;
    });
  }

  async function handleExport() {
    setAttemptedExport(true);
    if (selected.size === 0) {
      return;
    }
    setError(false);
    setIsPending(true);
    try {
      const queryParts: string[] = [];
      const sectionsParam = buildSectionsParam(selected);
      if (sectionsParam) {
        queryParts.push(`sections=${sectionsParam}`);
      }
      if (schuljahrId != null) {
        queryParts.push(`schuljahr_id=${schuljahrId}`);
      }
      const query = queryParts.join("&");
      const path = `students/${studentId}/export.pdf${query ? `?${query}` : ""}`;
      const { blob, filename } = await apiDownload(path);

      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      setTimeout(() => URL.revokeObjectURL(url), 0);
    } catch {
      setError(true);
    } finally {
      setIsPending(false);
    }
  }

  return (
    <section className={styles.section}>
      <h3>PDF-Export</h3>
      {schuljahrName && <p>Export für Schuljahr {schuljahrName}</p>}
      <fieldset>
        <legend>Abschnitte</legend>
        {ALL_SECTIONS.map((section) => (
          <label key={section}>
            <input
              type="checkbox"
              aria-label={SECTION_LABELS[section]}
              checked={selected.has(section)}
              onChange={() => toggleSection(section)}
            />{" "}
            {SECTION_LABELS[section]}
          </label>
        ))}
      </fieldset>
      {attemptedExport && selected.size === 0 && (
        <p className={styles.formError}>Bitte mindestens einen Abschnitt auswählen.</p>
      )}
      <button type="button" onClick={handleExport} disabled={isPending}>
        PDF exportieren
      </button>
      {error && <p className={styles.formError}>Fehler beim Export — bitte erneut versuchen.</p>}
    </section>
  );
}
