export interface NavBereich {
  id: number;
  name: string;
}

export interface NavKlasse {
  id: number;
  name: string;
  bereich_id: number | null;
}

export interface NavSchuljahr {
  id: number;
  name: string;
  start_datum: string;
  end_datum: string;
}

export interface NavOptions {
  bereiche: NavBereich[];
  klassen: NavKlasse[];
  rolle: string;
  schuljahre: NavSchuljahr[];
  aktuelles_schuljahr_id: number | null;
}

export interface SchwellwertStufe {
  id?: number;
  stufe_nr: number;
  einheit: "fehltage" | "fehlstunden" | null;
  schwellenwert: number;
  fehlzeiten_filter: "nur_unentschuldigt" | "alle" | null;
  empfaenger_rollen: string[];
}

export interface ThresholdRule {
  id?: number;
  typ: "fehlzeiten" | "klassenbuch";
  geltungsbereich: "schulweit" | "abteilung";
  abteilung_id: number | null;
  stufen: SchwellwertStufe[];
}

export interface MeasureType {
  id?: number;
  name: string;
  setzt_zaehler_zurueck: boolean;
  aktiv: boolean;
}

export interface ExcuseStatus {
  id: number;
  name: string;
  long_name: string | null;
  zaehlt_als_entschuldigt: boolean;
  aktiv: boolean;
}

export interface SyncSettings {
  sync_interval_cron: string;
  schuljahr_start_cache: string | null;
  letzter_sync_am: string | null;
  aktuelles_schuljahr: { id: number; name: string } | null;
}

export interface Abteilung {
  id: number;
  name: string;
}

export interface StatsOwn {
  anzahl_schueler: number;
  avg_fehltage: number;
  avg_fehlstunden: number;
  avg_klassenbuch: number;
  anzahl_klassenbuch: number;
  anzahl_massnahmen: number;
}

export interface StatsVergleichEintrag extends StatsOwn {
  id: number;
  name: string;
}

export interface StatsContext {
  bereich_id: number | null;
  bereich_name: string | null;
  klasse_id: number | null;
  klasse_name: string | null;
}

export type StatsLevel = "schule" | "eigene_bereiche" | "bereich" | "eigene_klassen" | "klasse";

export interface Stats {
  level: StatsLevel;
  context: StatsContext;
  own: StatsOwn;
  vergleich: StatsVergleichEintrag[];
}

export interface Klasse {
  id: number;
  name: string;
}

export interface Zaehlerstand {
  aktueller_stand: number;
  erreichte_stufe_nr: number | null;
}

export interface BenachrichtigungEmpfaenger {
  rolle: string;
  name?: string;
  [key: string]: unknown;
}

export interface Benachrichtigung {
  id: number;
  regel_id: number | null;
  typ: string | null;
  stufe_nr: number;
  gesendet_am: string;
  empfaenger: BenachrichtigungEmpfaenger[];
  status: string;
}

export interface StudentOverview {
  id: number;
  vorname: string;
  nachname: string;
  klasse: Klasse | null;
  zaehlerstand: Record<string, Zaehlerstand> | null;
  letzte_benachrichtigung: Benachrichtigung | null;
  ohne_massnahme_seit_benachrichtigung: boolean | null;
  fehltage: number | null;
  fehlstunden: number | null;
  klassenbuch_anzahl: number | null;
}

export interface StudentList {
  items: StudentOverview[];
  total: number;
  limit: number;
  offset: number;
}

export interface Fehlzeit {
  id: number;
  typ: string;
  datum: string;
  start_zeit: number;
  end_zeit: number;
  fach: string | null;
  excuse_status_id: number | null;
  grund_text: string | null;
}

export interface KlassenbuchEintrag {
  id: number;
  kategorie_id: number;
  datum: string;
  text: string | null;
  lesson_id: number | null;
}

export interface Massnahme {
  id: number;
  massnahmen_typ_id: number;
  massnahmen_typ_name: string;
  datum: string;
  notiz: string | null;
  erfasst_von_nutzer_id: number;
  erfasst_von_name: string;
}

export interface Ausnahme {
  id: number;
  kategorie: "fehlzeiten" | "klassenbuch";
  grund: string;
  gueltig_bis: string | null;
  aktiv: boolean;
}

export interface StudentDetail {
  id: number;
  vorname: string;
  nachname: string;
  klasse: Klasse | null;
  zaehlerstand: Record<string, Zaehlerstand>;
  fehlzeiten: Fehlzeit[];
  klassenbuch: KlassenbuchEintrag[];
  massnahmen: Massnahme[];
  ausnahmen: Ausnahme[];
  benachrichtigungen: Benachrichtigung[];
}

export interface MassnahmenTyp {
  id: number;
  name: string;
}

export interface ExcuseStatusCatalogEntry {
  id: number;
  name: string;
  long_name: string | null;
}

export interface ClassregCategoryCatalogEntry {
  id: number;
  name: string;
  long_name: string | null;
}

export interface StudentCatalog {
  massnahmen_typen: MassnahmenTyp[];
  excuse_statuses: ExcuseStatusCatalogEntry[];
  classreg_categories: ClassregCategoryCatalogEntry[];
}
