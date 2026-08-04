import type { ThresholdRule } from "../../api/types";

export interface ThresholdRuleValidationError {
  ruleIndex: number;
  stufeIndex: number;
  message: string;
}

/**
 * Clientseitige Vorprüfung der Schwellwert-Regeln vor dem Speichern. Deckt aktuell den Fall ab,
 * der bisher erst als 422 vom Backend zurückkam (`threshold_rule_service.py`,
 * "empfaenger_rollen must not be empty"): eine Stufe ohne ausgewählten Empfänger. So bekommt man
 * den Hinweis direkt an der betroffenen Stufe statt eines generischen Fehlers nach dem Roundtrip.
 */
export function validateThresholdRules(rules: ThresholdRule[]): ThresholdRuleValidationError[] {
  const errors: ThresholdRuleValidationError[] = [];
  rules.forEach((rule, ruleIndex) => {
    rule.stufen.forEach((stufe, stufeIndex) => {
      if (stufe.empfaenger_rollen.length === 0) {
        errors.push({
          ruleIndex,
          stufeIndex,
          message: "Bitte mindestens einen Empfänger auswählen.",
        });
      }
    });
  });
  return errors;
}
