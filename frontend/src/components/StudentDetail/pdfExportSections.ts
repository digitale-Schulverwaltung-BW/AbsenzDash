export const ALL_SECTIONS = ["fehlzeiten", "klassenbuch", "massnahmen", "ausnahmen", "benachrichtigungen"] as const;

/**
 * Baut den sections-Query-Param aus den angehakten Checkboxen. Sind alle angehakt (Normalfall),
 * wird der Parameter weggelassen -- entspricht dem Backend-Default und ergibt eine kuerzere URL.
 */
export function buildSectionsParam(selected: Set<string>): string | undefined {
  if (selected.size === ALL_SECTIONS.length) {
    return undefined;
  }
  return Array.from(selected).join(",");
}
