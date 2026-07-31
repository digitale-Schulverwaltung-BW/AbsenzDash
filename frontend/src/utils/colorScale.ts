const DUNKELROT: [number, number, number] = [153, 27, 27];
const DUNKELGELB: [number, number, number] = [161, 98, 7];
const DUNKELGRUEN: [number, number, number] = [22, 101, 52];

function mische(von: [number, number, number], nach: [number, number, number], anteil: number): string {
  const [r1, g1, b1] = von;
  const [r2, g2, b2] = nach;
  const r = Math.round(r1 + (r2 - r1) * anteil);
  const g = Math.round(g1 + (g2 - g1) * anteil);
  const b = Math.round(b1 + (b2 - b1) * anteil);
  return `rgb(${r}, ${g}, ${b})`;
}

/**
 * Ordnet einen Wert innerhalb von [min, max] einer Farbe auf der Skala
 * dunkelgrün (min, "gut") -> dunkelgelb (Mitte) -> dunkelrot (max, "schlecht") zu.
 * min === max (keine Spannweite) wird als grün gewertet, nicht als Sonderfall behandelt.
 */
export function valueToColor(value: number, min: number, max: number): string {
  if (min === max) {
    return mische(DUNKELGRUEN, DUNKELGRUEN, 0);
  }
  const anteil = Math.min(1, Math.max(0, (value - min) / (max - min)));
  if (anteil <= 0.5) {
    return mische(DUNKELGRUEN, DUNKELGELB, anteil / 0.5);
  }
  return mische(DUNKELGELB, DUNKELROT, (anteil - 0.5) / 0.5);
}
