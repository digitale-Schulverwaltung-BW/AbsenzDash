import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { EskalationsBadge } from "./EskalationsBadge";

describe("EskalationsBadge", () => {
  it("renders the stufe number", () => {
    render(<EskalationsBadge stufeNr={2} maxStufeNr={3} />);
    expect(screen.getByText("2")).toBeInTheDocument();
  });

  it("renders a dash for null (keine Stufe erreicht)", () => {
    render(<EskalationsBadge stufeNr={null} maxStufeNr={3} />);
    expect(screen.getByText("–")).toBeInTheDocument();
  });

  it("colors stufe 0/null green and the max stufe dark red", () => {
    const { container: gruen } = render(<EskalationsBadge stufeNr={null} maxStufeNr={3} />);
    const { container: rot } = render(<EskalationsBadge stufeNr={3} maxStufeNr={3} />);

    const gruenStyle = (gruen.firstChild as HTMLElement).style.backgroundColor;
    const rotStyle = (rot.firstChild as HTMLElement).style.backgroundColor;

    expect(gruenStyle).not.toBe(rotStyle);
  });
});
