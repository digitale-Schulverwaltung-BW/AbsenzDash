export interface NavBereich {
  id: number;
  name: string;
}

export interface NavKlasse {
  id: number;
  name: string;
  bereich_id: number | null;
}

export interface NavOptions {
  bereiche: NavBereich[];
  klassen: NavKlasse[];
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
