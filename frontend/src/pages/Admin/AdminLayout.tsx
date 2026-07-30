import { Link, Outlet, useLocation } from "react-router-dom";
import styles from "./AdminLayout.module.css";

const TABS = [
  { path: "/admin/schwellwerte", label: "Schwellwert-Regeln" },
  { path: "/admin/massnahmen", label: "Maßnahmen-Katalog" },
  { path: "/admin/entschuldigungsstatus", label: "Entschuldigungsstatus" },
  { path: "/admin/sync", label: "Sync-Einstellungen" },
];

export function AdminLayout() {
  const location = useLocation();
  return (
    <div>
      <nav className={styles.subnav}>
        {TABS.map((tab) => (
          <Link
            key={tab.path}
            to={tab.path}
            className={location.pathname === tab.path ? styles.subtabActive : styles.subtab}
          >
            {tab.label}
          </Link>
        ))}
      </nav>
      <Outlet />
    </div>
  );
}
