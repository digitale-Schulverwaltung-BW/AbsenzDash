import { describe, expect, it } from "vitest";
import { valueToColor } from "./colorScale";

describe("valueToColor", () => {
  it("returns green for the minimum value", () => {
    expect(valueToColor(0, 0, 10)).toBe("rgb(22, 101, 52)");
  });

  it("returns red for the maximum value", () => {
    expect(valueToColor(10, 0, 10)).toBe("rgb(153, 27, 27)");
  });

  it("returns yellow for the midpoint", () => {
    expect(valueToColor(5, 0, 10)).toBe("rgb(161, 98, 7)");
  });

  it("returns green when min equals max", () => {
    expect(valueToColor(4, 4, 4)).toBe("rgb(22, 101, 52)");
  });

  it("clamps values outside the [min, max] range", () => {
    expect(valueToColor(-5, 0, 10)).toBe(valueToColor(0, 0, 10));
    expect(valueToColor(15, 0, 10)).toBe(valueToColor(10, 0, 10));
  });
});
