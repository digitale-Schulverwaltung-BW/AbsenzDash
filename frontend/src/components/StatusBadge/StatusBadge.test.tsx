import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StatusBadge, stufeToTone } from "./StatusBadge";

describe("StatusBadge", () => {
  it("renders the given label", () => {
    render(<StatusBadge label="Stufe 2" tone="stufe2" />);
    expect(screen.getByText("Stufe 2")).toBeInTheDocument();
  });
});

describe("stufeToTone", () => {
  it("maps null to neutral and stufe numbers to their tone, capping at stufe3", () => {
    expect(stufeToTone(null)).toBe("neutral");
    expect(stufeToTone(1)).toBe("stufe1");
    expect(stufeToTone(2)).toBe("stufe2");
    expect(stufeToTone(3)).toBe("stufe3");
    expect(stufeToTone(5)).toBe("stufe3");
  });
});
