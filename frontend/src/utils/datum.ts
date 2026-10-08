/** "YYYY-MM-DD" -> "TT.MM.JJJJ"; unbekannte Formate werden unverändert zurückgegeben. */
export function formatDatumDe(iso: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!match) return iso;
  return `${match[3]}.${match[2]}.${match[1]}`;
}

/** Heutiges Datum (lokal) als "YYYY-MM-DD". */
export function heuteIso(now: Date = new Date()): string {
  const monat = String(now.getMonth() + 1).padStart(2, "0");
  const tag = String(now.getDate()).padStart(2, "0");
  return `${now.getFullYear()}-${monat}-${tag}`;
}
