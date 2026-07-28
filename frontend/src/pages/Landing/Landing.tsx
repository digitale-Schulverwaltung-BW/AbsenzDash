import { useSearchParams } from "react-router-dom";
import { useStats } from "../../api/hooks/useStats";
import { ComparisonChart } from "../../components/ComparisonChart/ComparisonChart";
import { StatCard } from "../../components/StatCard/StatCard";

export function Landing() {
  const [searchParams] = useSearchParams();
  const bereichParam = searchParams.get("bereich");
  const klasseParam = searchParams.get("klasse");
  const bereichId = bereichParam ? Number(bereichParam) : null;
  const klasseId = klasseParam ? Number(klasseParam) : null;

  const { data, isLoading, isError } = useStats(bereichId, klasseId);

  if (isLoading) {
    return <p>Lädt Kennzahlen…</p>;
  }
  if (isError || !data) {
    return <p>Fehler beim Laden der Kennzahlen.</p>;
  }

  return (
    <div>
      <StatCard label="Ø Fehltage" value={data.own.avg_fehltage.toFixed(1)} />
      <StatCard label="Ø Fehlstunden" value={data.own.avg_fehlstunden.toFixed(1)} />
      <StatCard
        label="Klassenbuch-Einträge"
        value={data.own.avg_klassenbuch.toFixed(1)}
        secondaryValue={`${data.own.anzahl_klassenbuch} gesamt`}
      />
      <StatCard label="Maßnahmen" value={String(data.own.anzahl_massnahmen)} />
      <ComparisonChart data={data.vergleich} metric="avg_fehltage" />
    </div>
  );
}
