type HSL = [hue: number, saturation: number, lightness: number];

// HSL statt RGB interpoliert: Gruen/Gelb/Rot in RGB liegen sich im Gruen-Kanal fast gleich (~100),
// wodurch eine RGB-Mischung durch ein mattes Oliv/Braun statt durch klares Gelb laeuft. Bei
// gleichbleibender Saettigung/Helligkeit und nur wanderndem Farbton bleibt jede Zwischenstufe klar
// erkennbar gruen/gelb/rot.
const DUNKELGRUEN: HSL = [142, 71, 33];
const DUNKELGELB: HSL = [38, 92, 33];
const DUNKELROT: HSL = [0, 70, 35];

function mische(von: HSL, nach: HSL, anteil: number): string {
  const h = Math.round(von[0] + (nach[0] - von[0]) * anteil);
  const s = Math.round(von[1] + (nach[1] - von[1]) * anteil);
  const l = Math.round(von[2] + (nach[2] - von[2]) * anteil);
  return `hsl(${h}, ${s}%, ${l}%)`;
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
