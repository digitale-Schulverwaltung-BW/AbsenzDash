import styles from "./StatusBadge.module.css";

export type StatusBadgeTone = "neutral" | "info" | "stufe1" | "stufe2" | "stufe3";

interface StatusBadgeProps {
  label: string;
  tone: StatusBadgeTone;
}

export function StatusBadge({ label, tone }: StatusBadgeProps) {
  return <span className={`${styles.badge} ${styles[tone]}`}>{label}</span>;
}

export function stufeToTone(stufeNr: number | null): "neutral" | "stufe1" | "stufe2" | "stufe3" {
  if (stufeNr === null || stufeNr < 1) return "neutral";
  if (stufeNr === 1) return "stufe1";
  if (stufeNr === 2) return "stufe2";
  return "stufe3";
}
