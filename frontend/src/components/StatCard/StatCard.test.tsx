import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StatCard } from "./StatCard";

describe("StatCard", () => {
  it("shows the label and value", () => {
    render(<StatCard label="Ø Fehltage" value="2.3" />);
    expect(screen.getByText("Ø Fehltage")).toBeInTheDocument();
    expect(screen.getByText("2.3")).toBeInTheDocument();
  });

  it("shows the secondary value in parentheses when provided", () => {
    render(<StatCard label="Klassenbuch-Einträge" value="0.8" secondaryValue="120 gesamt" />);
    expect(screen.getByText("(120 gesamt)")).toBeInTheDocument();
  });
});
