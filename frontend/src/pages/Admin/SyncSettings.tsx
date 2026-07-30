import { useEffect, useState } from "react";
import { useSyncSettings } from "../../api/hooks/useSyncSettings";
import { useUpdateSyncSettings } from "../../api/hooks/useUpdateSyncSettings";
import { useTriggerSyncNow } from "../../api/hooks/useTriggerSyncNow";
import styles from "../../components/StudentDetail/StudentDetail.module.css";

export function SyncSettings() {
  const { data, isLoading, isError } = useSyncSettings();
  const { mutate: updateSettings, isPending: isSaving, error: saveError } = useUpdateSyncSettings();
  const { mutate: triggerSync, isPending: isSyncing, isSuccess: syncSucceeded, error: syncError } = useTriggerSyncNow();
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
      <button type="button" onClick={() => triggerSync()} disabled={isSyncing}>
        Sync jetzt ausführen
      </button>
      {syncSucceeded && <p>Sync erfolgreich ausgeführt.</p>}
      {syncError && <p className={styles.formError}>Sync fehlgeschlagen.</p>}
    </section>
  );
}
