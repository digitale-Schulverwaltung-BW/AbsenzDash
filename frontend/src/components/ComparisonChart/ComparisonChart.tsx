import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { StatsVergleichEintrag } from "../../api/types";
import { valueToColor } from "../../utils/colorScale";

interface ComparisonChartProps {
  data: StatsVergleichEintrag[];
  metric: "avg_fehltage" | "avg_fehlstunden" | "avg_klassenbuch" | "anzahl_massnahmen";
  onEntryClick?: (id: number) => void;
}

export function ComparisonChart({ data, metric, onEntryClick }: ComparisonChartProps) {
  if (data.length === 0) {
    return null;
  }

  const werte = data.map((eintrag) => eintrag[metric]);
  const min = Math.min(...werte);
  const max = Math.max(...werte);

  return (
    <ResponsiveContainer width="100%" height={240}>
      <BarChart data={data}>
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis dataKey="name" />
        <YAxis />
        <Tooltip />
        <Bar dataKey={metric}>
          {data.map((eintrag) => (
            <Cell
              key={eintrag.id}
              fill={valueToColor(eintrag[metric], min, max)}
              cursor={onEntryClick ? "pointer" : undefined}
              onClick={onEntryClick ? () => onEntryClick(eintrag.id) : undefined}
            />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
