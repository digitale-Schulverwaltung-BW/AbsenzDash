import type { StatsLevel } from "../../api/types";

export type EntryClickTarget = { typ: "bereich"; id: number } | { typ: "klasse"; id: number };

const BEREICH_EBENEN = new Set<StatsLevel>(["schule", "eigene_bereiche"]);

/**
 * Balken im Dashboard sind je nach StatsLevel entweder Bereiche oder Klassen (klasse-Ebene hat
 * nie vergleich-Eintraege, kommt hier also nie vor). Reine Entscheidungsfunktion, damit sie ohne
 * ResizeObserver/recharts-Rendering (in jsdom nicht verfuegbar) testbar ist.
 */
export function resolveEntryClickTarget(level: StatsLevel, id: number): EntryClickTarget {
  return BEREICH_EBENEN.has(level) ? { typ: "bereich", id } : { typ: "klasse", id };
}

/**
 * Baut die Such-Parameter fuer die Navigation von einem Balken-Klick auf eine Klasse zur
 * Schuelerliste. Uebernimmt `bereich`/`schuljahr` aus den aktuellen Parametern, damit die
 * Navigation (Tabs, Bereich-/Klassen-Dropdown) nach dem Wechsel weiterhin den Bereich kennt, aus
 * dem die Klasse aufgerufen wurde -- sonst zeigen Uebersicht-Tab (liest nur `klasse`) und
 * Navigation-Dropdowns (brauchen `bereich` UND `klasse`) inkonsistente Zustaende.
 */
export function buildKlasseNavigationParams(currentParams: URLSearchParams, klasseId: number): URLSearchParams {
  const zielParams = new URLSearchParams();
  zielParams.set("klasse", String(klasseId));
  const bereich = currentParams.get("bereich");
  if (bereich) {
    zielParams.set("bereich", bereich);
  }
  const schuljahr = currentParams.get("schuljahr");
  if (schuljahr) {
    zielParams.set("schuljahr", schuljahr);
  }
  return zielParams;
}
