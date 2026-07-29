import type { Benachrichtigung } from "../../api/types";
import { StatusBadge } from "../StatusBadge/StatusBadge";
import styles from "./NotificationFlyout.module.css";

interface NotificationFlyoutProps {
  benachrichtigung: Benachrichtigung | null;
}

const STATUS_TEXT: Record<string, string> = {
  kein_empfaenger: "Kein Empfänger ermittelbar",
  initial_import: "Aus initialem Datenimport übernommen",
};

export function NotificationFlyout({ benachrichtigung }: NotificationFlyoutProps) {
  if (benachrichtigung === null) {
    return <StatusBadge label="Keine Benachrichtigung" tone="neutral" />;
  }

  const hatEmpfaenger = benachrichtigung.empfaenger.length > 0;

  return (
    <span className={styles.wrapper} tabIndex={0}>
      <StatusBadge label="Benachrichtigt" tone="info" />
      <div className={styles.flyout} role="tooltip">
        {hatEmpfaenger ? (
          <ul>
            {benachrichtigung.empfaenger.map((empfaenger, index) => (
              <li key={index}>
                {empfaenger.name ? `${empfaenger.rolle}: ${empfaenger.name}` : empfaenger.rolle}
              </li>
            ))}
          </ul>
        ) : (
          <p>{STATUS_TEXT[benachrichtigung.status] ?? benachrichtigung.status}</p>
        )}
      </div>
    </span>
  );
}
