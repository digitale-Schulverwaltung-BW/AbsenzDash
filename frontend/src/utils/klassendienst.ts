import type { Klassendienst } from "../api/types";
import { formatDatumDe } from "./datum";

/** Hover-/Screenreader-Text: "<Bezeichnung>: <Erklärung> – seit TT.MM.JJJJ" (Erklärung entfällt, wenn leer). */
export function klassendienstText(dienst: Pick<Klassendienst, "bezeichnung" | "beschreibung" | "von">): string {
  const erklaerung = dienst.beschreibung?.trim();
  const kopf = erklaerung ? `${dienst.bezeichnung}: ${erklaerung}` : dienst.bezeichnung;
  return `${kopf} – seit ${formatDatumDe(dienst.von)}`;
}

export type KlassendienstStatus = "aktiv" | "zukünftig" | "beendet";

/** Status eines Zeitraums relativ zu `heute` ("YYYY-MM-DD"); `aktiv_heute` hat Vorrang. */
export function klassendienstStatus(
  dienst: Pick<Klassendienst, "aktiv_heute" | "von" | "bis">,
  heute: string,
): KlassendienstStatus {
  if (dienst.aktiv_heute) return "aktiv";
  if (dienst.von > heute) return "zukünftig";
  if (dienst.bis < heute) return "beendet";
  return "aktiv";
}
