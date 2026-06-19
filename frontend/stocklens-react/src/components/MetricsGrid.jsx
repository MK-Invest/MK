import {
  ResponsiveContainer,
  AreaChart,
  Area,
  CartesianGrid,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

const METRICS = [
  { key: "market_cap", label: "Market Cap", type: "money" },
  { key: "pe", label: "P/E", type: "multiple" },
  { key: "pb", label: "P/B", type: "multiple" },
  { key: "ps", label: "P/S", type: "multiple" },

  { key: "roe", label: "ROE", type: "percent" },
  { key: "roa", label: "ROA", type: "percent" },
  { key: "roic", label: "ROIC", type: "percent" },

  { key: "eps_growth", label: "EPS Growth", type: "percent" },
  { key: "dividend_yield", label: "Dividend Yield", type: "percent" },

  { key: "current_ratio", label: "Current Ratio", type: "multiple" },
  { key: "de_ratio", label: "D/E", type: "multiple" },

  { key: "fcf_yield", label: "FCF Yield", type: "percent" },
  { key: "ev_ebitda", label: "EV/EBITDA", type: "multiple" },

  { key: "volume", label: "Volume", type: "number" },
];

const CHARTS = [
  { key: "revenue", label: "Revenue" },
  { key: "net_income", label: "Net Income" },
  { key: "ebitda", label: "EBITDA" },
];

// Převede ISO datum konce kvartálu ("2024-03-31") na "Q1 '24"
function formatQuarterLabel(isoDate) {
  if (!isoDate) return "";
  const [year, month] = isoDate.split("-");
  const m = parseInt(month, 10);
  const quarter = Math.ceil(m / 3);
  const shortYear = year.slice(2);
  return `Q${quarter} '${shortYear}`;
}

export function MetricsGrid({ data }) {
  if (!data) return null;

  const fundamentals = data?.fundamentals ?? {};
  const metrics = data?.metrics ?? {};
  const technical = data?.technical ?? {};

  const ttm = {
    ...fundamentals,
    ...metrics?.ttm,
    ...technical,
    ...metrics?.trend,
  };

  const getValue = (key) =>
    metrics?.ttm?.[key] ??
    fundamentals?.[key] ??
    technical?.[key] ??
    metrics?.trend?.[key];

  const history = fundamentals?.history ?? {};

  const revenue = history?.revenue ?? [];
  const netIncome = history?.net_income ?? [];
  const operating = history?.operating_income ?? [];
  const depreciation = history?.depreciation ?? [];

  const quarters = revenue.map((r, i) => ({
    end: r?.end,
    revenue: r?.val ?? null,
    net_income: netIncome?.[i]?.val ?? null,
    ebitda:
      operating?.[i]?.val != null && depreciation?.[i]?.val != null
        ? operating[i].val + depreciation[i].val
        : null,
  }));

  const formatLarge = (n) => {
    if (n == null) return "—";
    if (Math.abs(n) >= 1e12) return `${(n / 1e12).toFixed(2)}T`;
    if (Math.abs(n) >= 1e9) return `${(n / 1e9).toFixed(2)}B`;
    if (Math.abs(n) >= 1e6) return `${(n / 1e6).toFixed(2)}M`;
    return n.toLocaleString();
  };

  const formatValue = (value, type) => {
    if (value == null) return "—";

    switch (type) {
      case "percent":
        return `${(value * 100).toFixed(1)}%`;
      case "multiple":
        return `${value.toFixed(1)}x`;
      case "money":
        return `$${formatLarge(value)}`;
      case "number":
        return formatLarge(value);
      default:
        return value;
    }
  };

  const buildChartData = (key) =>
    quarters
      .filter((q) => q[key] != null)
      .map((q) => ({
        date: formatQuarterLabel(q.end),
        value: q[key] / 1e9,
      }))
      .reverse();

  return (
    <div style={styles.wrapper}>
      <div style={styles.hero}>
        <div>
          <div style={styles.ticker}>{data?.ticker}</div>
          <div style={styles.subtitle}>StockLens Terminal</div>
        </div>

        <div>
          <div style={styles.marketCap}>
            {formatValue(ttm?.market_cap, "money")}
          </div>
          <div style={styles.marketCapLabel}>
            Market Capitalization
          </div>
        </div>
      </div>

      <div style={styles.metricsGrid}>
        {METRICS.map((metric) => (
          <div key={metric.key} style={styles.metricCard}>
            <div style={styles.metricLabel}>{metric.label}</div>
            <div style={styles.metricValue}>
              {formatValue(getValue(metric.key), metric.type)}
            </div>
          </div>
        ))}
      </div>

     {/* CHARTS */}
<div style={styles.chartGrid}>
  {CHARTS.map((chart) => {
    const chartData = buildChartData(chart.key);

    return (
      <div key={chart.key} style={styles.chartCard}>
        <div style={styles.chartTitle}>{chart.label}</div>

        <ResponsiveContainer width="100%" height={240}>
          <AreaChart data={chartData}>
            <defs>
              <linearGradient
                id={`gradient-${chart.key}`}
                x1="0"
                y1="0"
                x2="0"
                y2="1"
              >
                <stop offset="0%" stopColor="#22c55e" stopOpacity={0.35} />
                <stop offset="100%" stopColor="#22c55e" stopOpacity={0} />
              </linearGradient>
            </defs>

            <CartesianGrid stroke="#172033" vertical={false} />

            <XAxis
              dataKey="date"
              stroke="#475569"
              tickLine={false}
              axisLine={false}
              tick={{ fontSize: 11 }}
            />

            <YAxis
              stroke="#475569"
              tickLine={false}
              axisLine={false}
              tick={{ fontSize: 11 }}
            />

            <Tooltip
              contentStyle={{
                background: "#0b1020",
                border: "1px solid #1e293b",
                borderRadius: 14,
                color: "white",
              }}
            />

            <Area
              type="monotone"
              dataKey="value"
              stroke="#22c55e"
              fill={`url(#gradient-${chart.key})`}
              strokeWidth={2.5}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    );
  })}
</div>
    </div>
  );
}

const styles = {
  wrapper: {
    display: "flex",
    flexDirection: "column",
    gap: 18,
  },

  hero: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    background: "#0b1020",
    border: "1px solid #172033",
    borderRadius: 18,
    padding: 20,
    flexWrap: "wrap",
    gap: 12,
  },

  ticker: {
    fontSize: 34,
    fontWeight: 800,
    letterSpacing: "-1px",
  },

  subtitle: {
    marginTop: 4,
    color: "#64748b",
    fontSize: 13,
  },

  marketCap: {
    fontSize: 26,
    fontWeight: 700,
    textAlign: "right",
  },

  marketCapLabel: {
    color: "#64748b",
    marginTop: 4,
    fontSize: 12,
    textAlign: "right",
  },

  metricsGrid: {
    display: "flex",
    flexWrap: "wrap",
    gap: 12,
  },

  metricCard: {
    flex: "1 1 160px",
    minWidth: 150,
    background: "#0b1020",
    border: "1px solid #172033",
    borderRadius: 14,
    padding: 14,
  },

  metricLabel: {
    color: "#64748b",
    fontSize: 11,
    marginBottom: 10,
    textTransform: "uppercase",
    letterSpacing: 1,
  },

  metricValue: {
    fontSize: 22,
    fontWeight: 700,
  },

  chartGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))",
    gap: 14,
  },

  chartCard: {
    background: "#0b1020",
    border: "1px solid #172033",
    borderRadius: 18,
    padding: 16,
  },

  chartTitle: {
    fontSize: 16,
    fontWeight: 600,
    marginBottom: 12,
  },
};
