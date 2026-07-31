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
