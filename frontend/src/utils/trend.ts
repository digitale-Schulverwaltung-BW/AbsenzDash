export const TREND_TAGE_OPTIONEN = [7, 14, 30] as const;
export type TrendTage = (typeof TREND_TAGE_OPTIONEN)[number];

export function parseTrendTage(wert: string | null): TrendTage | null {
  const zahl = Number(wert);
  return (TREND_TAGE_OPTIONEN as readonly number[]).includes(zahl) ? (zahl as TrendTage) : null;
}
