import { useEffect, useState } from "react";
import { useAbteilungen } from "../../api/hooks/useAbteilungen";
import { useThresholdRules } from "../../api/hooks/useThresholdRules";
import { useUpdateThresholdRules } from "../../api/hooks/useUpdateThresholdRules";
import type { SchwellwertStufe, ThresholdRule } from "../../api/types";
import styles from "./ThresholdRules.module.css";
import sectionStyles from "../../components/StudentDetail/StudentDetail.module.css";
import { validateThresholdRules } from "./thresholdRuleValidation";

const ROLLEN = ["klassenlehrkraft", "bereichsleiter", "schulleitung"] as const;

function leereStufe(stufeNr: number, typ: ThresholdRule["typ"]): SchwellwertStufe {
  return {
    stufe_nr: stufeNr,
    einheit: typ === "fehlzeiten" ? "fehltage" : null,
    schwellenwert: 1,
    fehlzeiten_filter: typ === "fehlzeiten" ? "nur_unentschuldigt" : null,
    empfaenger_rollen: [],
  };
}

function leereRegel(): ThresholdRule {
  return { typ: "fehlzeiten", geltungsbereich: "schulweit", abteilung_id: null, stufen: [leereStufe(1, "fehlzeiten")] };
}

// Renumbers stufe_nr sequentially (1, 2, 3, ...) by array position, so that
// stufe_nr always matches visual order and stays free of gaps/duplicates
// regardless of prior add/remove history.
function renumberStufen(stufen: SchwellwertStufe[]): SchwellwertStufe[] {
  return stufen.map((stufe, index) => ({ ...stufe, stufe_nr: index + 1 }));
}

export function ThresholdRules() {
  const { data, isLoading, isError } = useThresholdRules();
  const { data: abteilungen } = useAbteilungen();
  const { mutate, isPending, error } = useUpdateThresholdRules();
  const [rules, setRules] = useState<ThresholdRule[]>([]);
  const [attemptedSave, setAttemptedSave] = useState(false);
  const validationErrors = validateThresholdRules(rules);

  useEffect(() => {
    if (data) {
      setRules(data);
    }
  }, [data]);

  if (isLoading) {
    return <p>Lädt…</p>;
  }
  if (isError || !data) {
    return <p>Fehler beim Laden der Schwellwert-Regeln.</p>;
  }

  function updateRule(index: number, patch: Partial<ThresholdRule>) {
    setRules((current) => current.map((rule, i) => (i === index ? { ...rule, ...patch } : rule)));
  }

  function updateStufe(ruleIndex: number, stufeIndex: number, patch: Partial<SchwellwertStufe>) {
    setRules((current) =>
      current.map((rule, i) =>
        i !== ruleIndex
          ? rule
          : { ...rule, stufen: rule.stufen.map((stufe, j) => (j === stufeIndex ? { ...stufe, ...patch } : stufe)) },
      ),
    );
  }

  function toggleRolle(ruleIndex: number, stufeIndex: number, rolle: string) {
    setRules((current) =>
      current.map((rule, i) =>
        i !== ruleIndex
          ? rule
          : {
              ...rule,
              stufen: rule.stufen.map((stufe, j) =>
                j !== stufeIndex
                  ? stufe
                  : {
                      ...stufe,
                      empfaenger_rollen: stufe.empfaenger_rollen.includes(rolle)
                        ? stufe.empfaenger_rollen.filter((r) => r !== rolle)
                        : [...stufe.empfaenger_rollen, rolle],
                    },
              ),
            },
      ),
    );
  }

  function addStufe(ruleIndex: number) {
    setRules((current) =>
      current.map((rule, i) =>
        i !== ruleIndex
          ? rule
          : { ...rule, stufen: renumberStufen([...rule.stufen, leereStufe(rule.stufen.length + 1, rule.typ)]) },
      ),
    );
  }

  function changeTyp(ruleIndex: number, typ: ThresholdRule["typ"]) {
    setRules((current) =>
      current.map((rule, i) =>
        i !== ruleIndex
          ? rule
          : {
              ...rule,
              typ,
              stufen: rule.stufen.map((stufe) => ({
                ...stufe,
                einheit: typ === "fehlzeiten" ? (stufe.einheit ?? "fehltage") : null,
                fehlzeiten_filter: typ === "fehlzeiten" ? (stufe.fehlzeiten_filter ?? "nur_unentschuldigt") : null,
              })),
            },
      ),
    );
  }

  function removeStufe(ruleIndex: number, stufeIndex: number) {
    setRules((current) =>
      current.map((rule, i) =>
        i !== ruleIndex
          ? rule
          : { ...rule, stufen: renumberStufen(rule.stufen.filter((_, j) => j !== stufeIndex)) },
      ),
    );
  }

  function removeRule(index: number) {
    setRules((current) => current.filter((_, i) => i !== index));
  }

  function addRule() {
    setRules((current) => [...current, leereRegel()]);
  }

  function handleSave() {
    setAttemptedSave(true);
    if (validationErrors.length > 0) {
      return;
    }
    mutate(rules);
  }

  return (
    <section className={sectionStyles.section}>
      <h3>Schwellwert-Regeln</h3>
      {rules.map((rule, ruleIndex) => (
        <div className={styles.rule} key={rule.id ?? `neu-${ruleIndex}`}>
          <label>
            Typ
            <select
              aria-label={`Typ Regel ${ruleIndex + 1}`}
              value={rule.typ}
              onChange={(event) => changeTyp(ruleIndex, event.target.value as ThresholdRule["typ"])}
            >
              <option value="fehlzeiten">Fehlzeiten</option>
              <option value="klassenbuch">Klassenbuch</option>
            </select>
          </label>
          <label>
            Geltungsbereich
            <select
              aria-label={`Geltungsbereich Regel ${ruleIndex + 1}`}
              value={rule.geltungsbereich}
              onChange={(event) =>
                updateRule(ruleIndex, {
                  geltungsbereich: event.target.value as ThresholdRule["geltungsbereich"],
                  abteilung_id: event.target.value === "schulweit" ? null : rule.abteilung_id,
                })
              }
            >
              <option value="schulweit">Schulweit</option>
              <option value="abteilung">Abteilung</option>
            </select>
          </label>
          {rule.geltungsbereich === "abteilung" && (
            <label>
              Abteilung
              <select
                aria-label={`Abteilung Regel ${ruleIndex + 1}`}
                value={rule.abteilung_id ?? ""}
                onChange={(event) => updateRule(ruleIndex, { abteilung_id: Number(event.target.value) })}
              >
                <option value="">Bitte wählen</option>
                {(abteilungen ?? []).map((abteilung) => (
                  <option key={abteilung.id} value={abteilung.id}>
                    {abteilung.name}
                  </option>
                ))}
              </select>
            </label>
          )}

          {rule.stufen.map((stufe, stufeIndex) => (
            <div className={styles.stufenRow} key={stufe.id ?? `neu-${stufeIndex}`}>
              <span>Stufe {stufe.stufe_nr}</span>
              {rule.typ === "fehlzeiten" && (
                <label>
                  Einheit
                  <select
                    aria-label={`Einheit Regel ${ruleIndex + 1} Stufe ${stufeIndex + 1}`}
                    value={stufe.einheit ?? "fehltage"}
                    onChange={(event) =>
                      updateStufe(ruleIndex, stufeIndex, { einheit: event.target.value as SchwellwertStufe["einheit"] })
                    }
                  >
                    <option value="fehltage">Fehltage</option>
                    <option value="fehlstunden">Fehlstunden</option>
                  </select>
                </label>
              )}
              <label>
                Schwellenwert
                <input
                  aria-label={`Schwellenwert Regel ${ruleIndex + 1} Stufe ${stufeIndex + 1}`}
                  type="number"
                  min={1}
                  value={stufe.schwellenwert}
                  onChange={(event) => updateStufe(ruleIndex, stufeIndex, { schwellenwert: Number(event.target.value) })}
                />
              </label>
              {rule.typ === "fehlzeiten" && (
                <label>
                  Filter
                  <select
                    aria-label={`Filter Regel ${ruleIndex + 1} Stufe ${stufeIndex + 1}`}
                    value={stufe.fehlzeiten_filter ?? "nur_unentschuldigt"}
                    onChange={(event) =>
                      updateStufe(ruleIndex, stufeIndex, {
                        fehlzeiten_filter: event.target.value as SchwellwertStufe["fehlzeiten_filter"],
                      })
                    }
                  >
                    <option value="nur_unentschuldigt">Nur unentschuldigt</option>
                    <option value="alle">Alle</option>
                  </select>
                </label>
              )}
              <fieldset>
                <legend>Empfänger</legend>
                {ROLLEN.map((rolle) => (
                  <label key={rolle}>
                    <input
                      type="checkbox"
                      aria-label={`${rolle} Regel ${ruleIndex + 1} Stufe ${stufeIndex + 1}`}
                      checked={stufe.empfaenger_rollen.includes(rolle)}
                      onChange={() => toggleRolle(ruleIndex, stufeIndex, rolle)}
                    />{" "}
                    {rolle}
                  </label>
                ))}
                {attemptedSave && stufe.empfaenger_rollen.length === 0 && (
                  <p className={sectionStyles.formError}>Bitte mindestens einen Empfänger auswählen.</p>
                )}
              </fieldset>
              <button type="button" onClick={() => removeStufe(ruleIndex, stufeIndex)}>
                Stufe entfernen
              </button>
            </div>
          ))}
          <button type="button" onClick={() => addStufe(ruleIndex)}>
            Stufe hinzufügen
          </button>
          <button type="button" onClick={() => removeRule(ruleIndex)}>
            Regel entfernen
          </button>
        </div>
      ))}
      <button type="button" onClick={addRule}>
        Neue Regel
      </button>
      <button type="button" onClick={handleSave} disabled={isPending}>
        Speichern
      </button>
      {attemptedSave && validationErrors.length > 0 && (
        <p className={sectionStyles.formError}>
          Bitte die markierten Stufen korrigieren, bevor gespeichert werden kann.
        </p>
      )}
      {error && <p className={sectionStyles.formError}>Fehler beim Speichern — Regeln prüfen (z.B. doppelte Abteilungs-Regel).</p>}
    </section>
  );
}
