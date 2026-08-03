import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { StatsVergleichEintrag } from "../../api/types";
import { valueToColor } from "../../utils/colorScale";

interface ComparisonChartProps {
  data: StatsVergleichEintrag[];
  metric: "avg_fehltage" | "avg_fehlstunden" | "avg_klassenbuch" | "anzahl_massnahmen";
  onEntryClick?: (id: number) => void;
}

const NEUTRALGRAU = "hsl(220, 9%, 75%)";

export function ComparisonChart({ data, metric, onEntryClick }: ComparisonChartProps) {
  if (data.length === 0) {
    return null;
  }

  // Bereiche/Klassen ohne aktive Schueler liefern eine technische 0 in jeder Kennzahl (siehe
  // _aggregate im Backend), keine echte "beste" Auspraegung -- die duerfen weder die Farb-Skala der
  // uebrigen Balken verzerren (min faellt sonst faelschlich auf 0) noch selbst gruen erscheinen.
  const bewertbar = data.filter((eintrag) => eintrag.anzahl_schueler > 0);
  const werte = bewertbar.map((eintrag) => eintrag[metric]);
  const min = werte.length > 0 ? Math.min(...werte) : 0;
  const max = werte.length > 0 ? Math.max(...werte) : 0;

  return (
    <ResponsiveContainer width="100%" height={240}>
      <BarChart data={data}>
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis dataKey="name" />
        <YAxis />
        <Tooltip />
        <Bar
          dataKey={metric}
          cursor={onEntryClick ? "pointer" : undefined}
          onClick={onEntryClick ? (eintrag: StatsVergleichEintrag) => onEntryClick(eintrag.id) : undefined}
        >
          {data.map((eintrag) => (
            <Cell key={eintrag.id} fill={eintrag.anzahl_schueler > 0 ? valueToColor(eintrag[metric], min, max) : NEUTRALGRAU} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
