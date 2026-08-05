import { valueToColor } from "../../utils/colorScale";
import styles from "./EskalationsBadge.module.css";

interface EskalationsBadgeProps {
  stufeNr: number | null;
  maxStufeNr: number;
}

export function EskalationsBadge({ stufeNr, maxStufeNr }: EskalationsBadgeProps) {
  const wert = stufeNr ?? 0;
  const farbe = valueToColor(wert, 0, Math.max(maxStufeNr, 1));
  return (
    <span className={styles.badge} style={{ backgroundColor: farbe }}>
      {stufeNr ?? "–"}
    </span>
  );
}
