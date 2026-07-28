import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { StatsVergleichEintrag } from "../../api/types";

interface ComparisonChartProps {
  data: StatsVergleichEintrag[];
  metric: "avg_fehltage" | "avg_fehlstunden" | "avg_klassenbuch" | "anzahl_massnahmen";
}

export function ComparisonChart({ data, metric }: ComparisonChartProps) {
  if (data.length === 0) {
    return null;
  }
  return (
    <ResponsiveContainer width="100%" height={240}>
      <BarChart data={data}>
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis dataKey="name" />
        <YAxis />
        <Tooltip />
        <Bar dataKey={metric} />
      </BarChart>
    </ResponsiveContainer>
  );
}
