import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";

export default function Charts({ data }) {
  const quarters = data?.metrics?.quarters ?? [];

  const chartData = quarters
    .filter(q => q.revenue != null)
    .map(q => ({
      date: q.end ? q.end.slice(0, 10) : "",
      revenue: q.revenue / 1e9,
      netIncome: q.net_income != null ? q.net_income / 1e9 : null,
      ebitda: q.ebitda != null ? q.ebitda / 1e9 : null,
    }))
    .reverse();

  if (!chartData.length) {
    return <div style={{ padding: 12 }}>No chart data</div>;
  }

  return (
    <div style={{ width: "100%", height: 300 }}>
      <h3 style={{ marginBottom: 10 }}>Financial Trends (B USD)</h3>

      <ResponsiveContainer width="100%" height={260}>
        <LineChart data={chartData}>
          <CartesianGrid stroke="#1f2937" strokeDasharray="3 3" />

          <XAxis
            dataKey="date"
            tick={{ fill: "#9ca3af", fontSize: 12 }}
          />

          <YAxis
            tick={{ fill: "#9ca3af", fontSize: 12 }}
          />

          <Tooltip
            contentStyle={{
              backgroundColor: "#111827",
              border: "1px solid #1f2937",
              color: "#fff",
            }}
          />

          <Line
            type="monotone"
            dataKey="revenue"
            stroke="#60a5fa"
            strokeWidth={2}
            dot={false}
            name="Revenue"
          />

          <Line
            type="monotone"
            dataKey="netIncome"
            stroke="#34d399"
            strokeWidth={2}
            dot={false}
            name="Net Income"
          />

          <Line
            type="monotone"
            dataKey="ebitda"
            stroke="#f59e0b"
            strokeWidth={2}
            dot={false}
            name="EBITDA"
          />

        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}