export interface AnonymerName {
  vorname: string;
  nachname: string;
}

// Feste, plausibel klingende Namen statt generierter Zufallswoerter - einfacher zu
// pflegen und garantiert lesbar/unauffaellig fuer Screenshots (siehe Diskussion
// 2026-08-06). Reine Anzeige-Kosmetik fuers Doku-Screenshot, keine echte
// Datenschutz-Massnahme - die realen Namen kommen weiterhin unveraendert per API.
const NAMEN: AnonymerName[] = [
  { vorname: "Max", nachname: "Mustermann" },
  { vorname: "Erika", nachname: "Musterfrau" },
  { vorname: "Markus", nachname: "Maier" },
  { vorname: "Sabine", nachname: "Schulze" },
  { vorname: "Peter", nachname: "Müller" },
  { vorname: "Anna", nachname: "Fischer" },
  { vorname: "Tobias", nachname: "Weber" },
  { vorname: "Julia", nachname: "Wagner" },
  { vorname: "Simon", nachname: "Becker" },
  { vorname: "Laura", nachname: "Hoffmann" },
  { vorname: "Jonas", nachname: "Schäfer" },
  { vorname: "Lena", nachname: "Koch" },
];

/**
 * Deterministisch: dieselbe schueler_id liefert immer denselben Fake-Namen, damit
 * ein Schueler ueber Schuelerliste und Detailseite hinweg (und bei mehreren
 * Screenshots) konsistent aussieht, ohne dass irgendwo Zustand gespeichert wird.
 */
export function anonymisiereName(schuelerId: number): AnonymerName {
  const index = schuelerId % NAMEN.length;
  return NAMEN[index];
}

export function istAnonymisierungAktiv(searchParams: URLSearchParams): boolean {
  return searchParams.get("a") === "1";
}
