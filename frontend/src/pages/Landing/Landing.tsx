import { useNavigate, useSearchParams } from "react-router-dom";
import { useStats } from "../../api/hooks/useStats";
import { ComparisonChart } from "../../components/ComparisonChart/ComparisonChart";
import { StatCard } from "../../components/StatCard/StatCard";
import { resolveEntryClickTarget } from "./entryClickTarget";

export function Landing() {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
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

  const scopeLabel = data.context.klasse_name ?? data.context.bereich_name ?? "Schulweit";

  const handleEntryClick = (id: number) => {
    const ziel = resolveEntryClickTarget(data.level, id);
    if (ziel.typ === "bereich") {
      const next = new URLSearchParams(searchParams);
      next.set("bereich", String(ziel.id));
      next.delete("klasse");
      setSearchParams(next);
      return;
    }
    const zielParams = new URLSearchParams();
    zielParams.set("klasse", String(ziel.id));
    const schuljahr = searchParams.get("schuljahr");
    if (schuljahr) {
      zielParams.set("schuljahr", schuljahr);
    }
    navigate({ pathname: "/schueler", search: zielParams.toString() });
  };

  return (
    <div>
      <h2>{scopeLabel}</h2>
      <section>
        <StatCard label="Ø Fehltage" value={data.own.avg_fehltage.toFixed(1)} />
        <ComparisonChart data={data.vergleich} metric="avg_fehltage" onEntryClick={handleEntryClick} />
      </section>
      <section>
        <StatCard label="Ø Fehlstunden" value={data.own.avg_fehlstunden.toFixed(1)} />
        <ComparisonChart data={data.vergleich} metric="avg_fehlstunden" onEntryClick={handleEntryClick} />
      </section>
      <section>
        <StatCard
          label="Klassenbuch-Einträge"
          value={data.own.avg_klassenbuch.toFixed(1)}
          secondaryValue={`${data.own.anzahl_klassenbuch} gesamt`}
        />
        <ComparisonChart data={data.vergleich} metric="avg_klassenbuch" onEntryClick={handleEntryClick} />
      </section>
      <section>
        <StatCard label="Maßnahmen" value={String(data.own.anzahl_massnahmen)} />
        <ComparisonChart data={data.vergleich} metric="anzahl_massnahmen" onEntryClick={handleEntryClick} />
      </section>
    </div>
  );
}
