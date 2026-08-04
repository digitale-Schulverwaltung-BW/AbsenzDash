import { describe, expect, it } from "vitest";
import type { ThresholdRule } from "../../api/types";
import { validateThresholdRules } from "./thresholdRuleValidation";

function regel(stufen: ThresholdRule["stufen"]): ThresholdRule {
  return { typ: "fehlzeiten", geltungsbereich: "schulweit", abteilung_id: null, stufen };
}

describe("validateThresholdRules", () => {
  it("returns no errors when every Stufe has at least one Empfänger", () => {
    const rules = [
      regel([
        { stufe_nr: 1, einheit: "fehltage", schwellenwert: 1, fehlzeiten_filter: "alle", empfaenger_rollen: ["klassenlehrkraft"] },
      ]),
    ];

    expect(validateThresholdRules(rules)).toEqual([]);
  });

  it("flags a Stufe with no Empfänger", () => {
    const rules = [
      regel([{ stufe_nr: 1, einheit: "fehltage", schwellenwert: 1, fehlzeiten_filter: "alle", empfaenger_rollen: [] }]),
    ];

    const errors = validateThresholdRules(rules);

    expect(errors).toHaveLength(1);
    expect(errors[0]).toMatchObject({ ruleIndex: 0, stufeIndex: 0 });
  });

  it("flags every offending Stufe across multiple Regeln", () => {
    const rules = [
      regel([
        { stufe_nr: 1, einheit: "fehltage", schwellenwert: 1, fehlzeiten_filter: "alle", empfaenger_rollen: [] },
        { stufe_nr: 2, einheit: "fehltage", schwellenwert: 2, fehlzeiten_filter: "alle", empfaenger_rollen: ["schulleitung"] },
      ]),
      regel([{ stufe_nr: 1, einheit: "fehltage", schwellenwert: 1, fehlzeiten_filter: "alle", empfaenger_rollen: [] }]),
    ];

    const errors = validateThresholdRules(rules);

    expect(errors).toEqual([
      { ruleIndex: 0, stufeIndex: 0, message: expect.any(String) },
      { ruleIndex: 1, stufeIndex: 0, message: expect.any(String) },
    ]);
  });
});
