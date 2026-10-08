import type { Klassendienst } from "../../api/types";
import { klassendienstText } from "../../utils/klassendienst";
import styles from "./KlassendienstBadge.module.css";

interface KlassendienstBadgesProps {
  klassendienste: Klassendienst[] | undefined;
}

/** Kürzel-Badges der heute gültigen Klassendienste (schreibgeschützte Anzeige aus WebUntis). */
export function KlassendienstBadges({ klassendienste }: KlassendienstBadgesProps) {
  const aktive = (klassendienste ?? []).filter((dienst) => dienst.aktiv_heute);
  if (aktive.length === 0) return null;
  return (
    <>
      {aktive.map((dienst) => {
        const text = klassendienstText(dienst);
        return (
          <span
            key={`${dienst.typ_id}-${dienst.von}`}
            role="img"
            tabIndex={0}
            aria-label={text}
            title={text}
            data-klassendienst={dienst.typ_id}
            className={styles.badge}
          >
            {dienst.kuerzel}
          </span>
        );
      })}
    </>
  );
}
