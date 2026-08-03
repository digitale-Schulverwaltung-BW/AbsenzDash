import { describe, expect, it } from "vitest";
import { valueToColor } from "./colorScale";

describe("valueToColor", () => {
  it("returns green for the minimum value", () => {
    expect(valueToColor(0, 0, 10)).toBe("hsl(142, 71%, 33%)");
  });

  it("returns red for the maximum value", () => {
    expect(valueToColor(10, 0, 10)).toBe("hsl(0, 70%, 35%)");
  });

  it("returns yellow for the midpoint", () => {
    expect(valueToColor(5, 0, 10)).toBe("hsl(38, 92%, 33%)");
  });

  it("returns green when min equals max", () => {
    expect(valueToColor(4, 4, 4)).toBe("hsl(142, 71%, 33%)");
  });

  it("clamps values outside the [min, max] range", () => {
    expect(valueToColor(-5, 0, 10)).toBe(valueToColor(0, 0, 10));
    expect(valueToColor(15, 0, 10)).toBe(valueToColor(10, 0, 10));
  });

  it("stays close to green shortly after the minimum instead of turning muddy", () => {
    const [hue] = /hsl\((\d+),/.exec(valueToColor(1, 0, 10))!.slice(1).map(Number);
    expect(hue).toBeGreaterThan(120);
  });
});
