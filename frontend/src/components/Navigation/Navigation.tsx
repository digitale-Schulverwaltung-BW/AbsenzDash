import { Link, useLocation, useSearchParams } from "react-router-dom";
import { useNavOptions } from "../../api/hooks/useNavOptions";
import styles from "./Navigation.module.css";

export function Navigation() {
  const { data, isLoading, isError } = useNavOptions();
  const [searchParams, setSearchParams] = useSearchParams();
  const location = useLocation();

  if (isLoading) {
    return <nav className={styles.nav}>Lädt Navigation…</nav>;
  }
  if (isError || !data) {
    return <nav className={styles.nav}>Fehler beim Laden der Navigation</nav>;
  }

  const bereichParam = searchParams.get("bereich");
  const selectedBereichId = bereichParam ? Number(bereichParam) : null;

  const showBereichDropdown = data.bereiche.length > 1;
  const visibleKlassen =
    data.bereiche.length === 0
      ? data.klassen
      : data.bereiche.length === 1
        ? data.klassen.filter((k) => k.bereich_id === data.bereiche[0].id)
        : selectedBereichId === null
          ? []
          : data.klassen.filter((k) => k.bereich_id === selectedBereichId);
  const showKlasseDropdown = visibleKlassen.length > 1;

  function handleBereichChange(value: string) {
    const next = new URLSearchParams(searchParams);
    if (value === "") {
      next.delete("bereich");
    } else {
      next.set("bereich", value);
    }
    next.delete("klasse");
    setSearchParams(next);
  }

  function handleKlasseChange(value: string) {
    const next = new URLSearchParams(searchParams);
    if (value === "") {
      next.delete("klasse");
    } else {
      next.set("klasse", value);
    }
    setSearchParams(next);
  }

  return (
    <nav className={styles.nav}>
      <div className={styles.tabs}>
        <Link
          to={{ pathname: "/", search: location.search }}
          className={location.pathname === "/" ? styles.tabActive : styles.tab}
        >
          Übersicht
        </Link>
        <Link
          to={{ pathname: "/schueler", search: location.search }}
          className={location.pathname === "/schueler" ? styles.tabActive : styles.tab}
        >
          Schülerliste
        </Link>
      </div>
      {showBereichDropdown && (
        <select
          aria-label="Bereich"
          value={bereichParam ?? ""}
          onChange={(event) => handleBereichChange(event.target.value)}
        >
          <option value="">Alle Bereiche</option>
          {data.bereiche.map((bereich) => (
            <option key={bereich.id} value={bereich.id}>
              {bereich.name}
            </option>
          ))}
        </select>
      )}
      {showKlasseDropdown && (
        <select
          aria-label="Klasse"
          value={searchParams.get("klasse") ?? ""}
          onChange={(event) => handleKlasseChange(event.target.value)}
        >
          <option value="">Alle Klassen</option>
          {visibleKlassen.map((klasse) => (
            <option key={klasse.id} value={klasse.id}>
              {klasse.name}
            </option>
          ))}
        </select>
      )}
    </nav>
  );
}
