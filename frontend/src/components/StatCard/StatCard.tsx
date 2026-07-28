import styles from "./StatCard.module.css";

interface StatCardProps {
  label: string;
  value: string;
  secondaryValue?: string;
}

export function StatCard({ label, value, secondaryValue }: StatCardProps) {
  return (
    <div className={styles.card}>
      <span className={styles.label}>{label}</span>
      <span className={styles.value}>{value}</span>
      {secondaryValue !== undefined && <span className={styles.secondary}>({secondaryValue})</span>}
    </div>
  );
}
