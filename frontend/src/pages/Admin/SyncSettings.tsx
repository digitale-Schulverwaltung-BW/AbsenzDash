import { useEffect, useState } from "react";
import { ApiError } from "../../api/client";
import { useSyncSettings } from "../../api/hooks/useSyncSettings";
import { useSyncStatus } from "../../api/hooks/useSyncStatus";
import { useUpdateSyncSettings } from "../../api/hooks/useUpdateSyncSettings";
import { useTriggerSyncNow } from "../../api/hooks/useTriggerSyncNow";
import { formatUhrzeitDe } from "../../utils/datum";
import styles from "../../components/StudentDetail/StudentDetail.module.css";

const STATUS_TEXT: Record<string, string> = { ok: "ok", fehler: "Fehler", abgebrochen: "abgebrochen" };

export function SyncSettings() {
  const { data, isLoading, isError } = useSyncSettings();
  const { mutate: updateSettings, isPending: isSaving, error: saveError } = useUpdateSyncSettings();
  const { mutate: triggerSync, isPending: isStarting, error: startError } = useTriggerSyncNow();
  const { data: status } = useSyncStatus();
  const laeuft = status?.laeuft ?? false;
  const aktuell = status?.aktueller_lauf ?? null;
  const letzter = status?.letzter_lauf ?? null;
  const [cron, setCron] = useState("");

  useEffect(() => {
    if (data) {
      setCron(data.sync_interval_cron);
    }
  }, [data]);

  if (isLoading) {
    return <p>Lädt…</p>;
  }
  if (isError || !data) {
    return <p>Fehler beim Laden der Sync-Einstellungen.</p>;
  }

  return (
    <section className={styles.section}>
      <h3>Sync-Einstellungen</h3>
      <form
        className={styles.form}
        onSubmit={(event) => {
          event.preventDefault();
          updateSettings(cron);
        }}
      >
        <label>
          Sync-Intervall (Cron-Ausdruck)
          <input aria-label="Sync-Intervall" type="text" value={cron} onChange={(event) => setCron(event.target.value)} required />
        </label>
        <button type="submit" disabled={isSaving}>
          Speichern
        </button>
        {saveError && <p className={styles.formError}>Fehler beim Speichern — Cron-Ausdruck prüfen.</p>}
      </form>
      <p>Schuljahresbeginn: {data.schuljahr_start_cache ?? "unbekannt (kein aktives Schuljahr in WebUntis)"}</p>
      <p>Letzter Sync: {data.letzter_sync_am ?? "noch nie"}</p>
      <p>
        Für den Sync verwendetes Schuljahr:{" "}
        {data.aktuelles_schuljahr ? data.aktuelles_schuljahr.name : "unbekannt (noch kein erfolgreicher Sync)"}
      </p>
      <button type="button" onClick={() => triggerSync()} disabled={isStarting || laeuft}>
        Sync jetzt ausführen
      </button>
      {startError && (
        <p className={styles.formError}>
          {startError instanceof ApiError && startError.status === 409
            ? "Ein Sync läuft bereits."
            : "Sync konnte nicht gestartet werden."}
        </p>
      )}
      {laeuft && aktuell && (
        <p role="status">
          Sync läuft seit {formatUhrzeitDe(aktuell.gestartet_am)}
          {aktuell.phase ? ` (Phase: ${aktuell.phase})` : ""}
        </p>
      )}
      {!laeuft && letzter && (
        <>
          <p>
            Letzter Sync-Lauf: {STATUS_TEXT[letzter.status] ?? letzter.status} ({formatUhrzeitDe(letzter.gestartet_am)},{" "}
            {letzter.ausgeloest_von === "zeitplan" ? "Zeitplan" : "manuell"})
          </p>
          {letzter.status === "fehler" && (
            <p className={styles.formError}>
              {letzter.fehler_kurz ? `${letzter.fehler_kurz} — ` : ""}Details siehe Server-Log.
            </p>
          )}
        </>
      )}
    </section>
  );
}
