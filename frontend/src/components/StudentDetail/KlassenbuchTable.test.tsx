import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { KlassenbuchTable } from "./KlassenbuchTable";

describe("KlassenbuchTable", () => {
  it("resolves kategorie_id to its long_name", () => {
    render(
      <KlassenbuchTable
        eintraege={[{ id: 1, kategorie_id: 3, datum: "2026-02-01", text: "Gestört", lesson_id: 1 }]}
        classregCategories={[{ id: 3, name: "LSU", long_name: "Lehrstoffunterbrechung" }]}
      />,
    );

    expect(screen.getByText("Lehrstoffunterbrechung")).toBeInTheDocument();
    expect(screen.getByText("Gestört")).toBeInTheDocument();
  });
});
