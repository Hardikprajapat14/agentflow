import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { ChartSpec } from "../types";

const COLORS = ["#4f46e5", "#e11d48", "#059669", "#d97706", "#7c3aed", "#0891b2", "#db2777", "#65a30d"];

export default function ChartCard({ spec }: { spec: ChartSpec }) {
  const common = { data: spec.data, margin: { top: 8, right: 16, left: 8, bottom: 8 } };
  return (
    <div className="card p-4">
      <h4 className="mb-2 font-semibold">{spec.title}</h4>
      <div className="h-72">
        <ResponsiveContainer width="100%" height="100%">
          {spec.type === "bar" ? (
            <BarChart {...common}>
              <CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="x" tick={{ fontSize: 11 }} /><YAxis tick={{ fontSize: 11 }} /><Tooltip />
              {spec.series.map((s, i) => <Bar key={s} dataKey={s} fill={COLORS[i % COLORS.length]} />)}
            </BarChart>
          ) : (
            <LineChart {...common}>
              <CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="x" tick={{ fontSize: 11 }} /><YAxis tick={{ fontSize: 11 }} /><Tooltip /><Legend />
              {spec.series.map((s, i) => <Line key={s} type="monotone" dataKey={s} stroke={COLORS[i % COLORS.length]} strokeWidth={2} dot={false} />)}
            </LineChart>
          )}
        </ResponsiveContainer>
      </div>
    </div>
  );
}
