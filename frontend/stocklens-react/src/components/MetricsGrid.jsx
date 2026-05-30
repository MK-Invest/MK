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
];

const CHARTS = [
  { key: "revenue", label: "Revenue" },
  { key: "net_income", label: "Net Income" },
  { key: "ebitda", label: "EBITDA" },
];

export function MetricsGrid({ data }) {
  if (!data) return null;

  const fundamentals = data?.fundamentals ?? {};
  const metrics = data?.metrics ?? {};
  const ttm = metrics?.ttm ?? {};
  const technical = data?.technical ?? {};

  const history = fundamentals?.history ?? {};

  const revenue = history?.revenue ?? [];
  const netIncome = history?.net_income ?? [];
  const operating = history?.operating_income ?? [];
  const depreciation = history?.depreciation ?? [];

  const demandZones = technical?.zones?.demand ?? [];
  const supplyZones = technical?.zones?.supply ?? [];

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
        date: q.end?.slice(2, 7),
        value: q[key] / 1e9,
      }))
      .reverse();

  return (
    <div style={styles.wrapper}>
      {/* HERO */}
      <div style={styles.hero}>
        <div>
          <div style={styles.ticker}>{data?.ticker}</div>
          <div style={styles.subtitle}>Stock Terminal</div>
        </div>

        <div>
          <div style={styles.price}>
            ${data?.price?.toFixed(2)}
          </div>
          <div style={styles.priceLabel}>Price</div>
        </div>

        <div>
          <div style={styles.marketCap}>
            {formatValue(ttm?.market_cap, "money")}
          </div>
          <div style={styles.marketCapLabel}>Market Cap</div>
        </div>
      </div>

      {/* METRICS */}
      <div style={styles.metricsGrid}>
        {METRICS.map((m) => (
          <div key={m.key} style={styles.metricCard}>
            <div style={styles.metricLabel}>{m.label}</div>
            <div style={styles.metricValue}>
              {formatValue(ttm?.[m.key], m.type)}
            </div>
          </div>
        ))}
      </div>

      {/* FUNDAMENTALS */}
      <div style={styles.section}>
        <div style={styles.sectionTitle}>Financial Summary</div>

        <div style={styles.metricsGrid}>
          <div style={styles.metricCard}>
            <div style={styles.metricLabel}>Revenue</div>
            <div style={styles.metricValue}>
              {formatLarge(fundamentals.revenue)}
            </div>
          </div>

          <div style={styles.metricCard}>
            <div style={styles.metricLabel}>Net Income</div>
            <div style={styles.metricValue}>
              {formatLarge(fundamentals.net_income)}
            </div>
          </div>

          <div style={styles.metricCard}>
            <div style={styles.metricLabel}>FCF</div>
            <div style={styles.metricValue}>
              {formatLarge(fundamentals.fcf)}
            </div>
          </div>

          <div style={styles.metricCard}>
            <div style={styles.metricLabel}>EBITDA Margin</div>
            <div style={styles.metricValue}>
              {(fundamentals.ebitda_margin * 100).toFixed(1)}%
            </div>
          </div>
        </div>
      </div>

      {/* TECHNICAL */}
      <div style={styles.section}>
        <div style={styles.sectionTitle}>Technical Analysis</div>

        <div style={styles.metricsGrid}>
          <div style={styles.metricCard}>
            <div style={styles.metricLabel}>RSI</div>
            <div style={styles.metricValue}>{technical.rsi}</div>
          </div>

          <div style={styles.metricCard}>
            <div style={styles.metricLabel}>EMA 20</div>
            <div style={styles.metricValue}>
              ${technical.ema_20?.toFixed(2)}
            </div>
          </div>

          <div style={styles.metricCard}>
            <div style={styles.metricLabel}>SMA 50</div>
            <div style={styles.metricValue}>
              ${technical.sma_50?.toFixed(2)}
            </div>
          </div>

          <div style={styles.metricCard}>
            <div style={styles.metricLabel}>SMA 200</div>
            <div style={styles.metricValue}>
              ${technical.sma_200?.toFixed(2)}
            </div>
          </div>

          <div style={styles.metricCard}>
            <div style={styles.metricLabel}>Trend</div>
            <div style={styles.metricValue}>
              {technical.trend}
            </div>
          </div>
        </div>
      </div>

      {/* CHARTS */}
      <div style={styles.chartGrid}>
        {CHARTS.map((c) => (
          <div key={c.key} style={styles.chartCard}>
            <div style={styles.chartTitle}>{c.label}</div>

            <ResponsiveContainer width="100%" height={240}>
              <AreaChart data={buildChartData(c.key)}>
                <CartesianGrid stroke="#172033" vertical={false} />
                <XAxis dataKey="date" stroke="#475569" />
                <YAxis stroke="#475569" />
                <Tooltip />

                <Area
                  type="monotone"
                  dataKey="value"
                  stroke="#22c55e"
                  fill="#22c55e"
                  fillOpacity={0.2}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        ))}
      </div>

      {/* QUARTERS */}
      <div style={styles.tableCard}>
        <div style={styles.sectionTitle}>Quarterly Results</div>

        <table style={styles.table}>
          <thead>
            <tr>
              <th>Date</th>
              <th>Revenue</th>
              <th>Net Income</th>
              <th>EBITDA</th>
            </tr>
          </thead>
          <tbody>
            {quarters.map((q) => (
              <tr key={q.end}>
                <td>{q.end}</td>
                <td>{formatLarge(q.revenue)}</td>
                <td>{formatLarge(q.net_income)}</td>
                <td>{formatLarge(q.ebitda)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* ZONES */}
      <div style={styles.chartGrid}>
        <div style={styles.chartCard}>
          <div style={styles.chartTitle}>Support Zones</div>
          {demandZones.map((z, i) => (
            <div key={i} style={styles.zoneRow}>
              <span>${z.price.toFixed(2)}</span>
              <span>{(z.strength * 100).toFixed(1)}%</span>
            </div>
          ))}
        </div>

        <div style={styles.chartCard}>
          <div style={styles.chartTitle}>Resistance Zones</div>
          {supplyZones.map((z, i) => (
            <div key={i} style={styles.zoneRow}>
              <span>${z.price.toFixed(2)}</span>
              <span>{(z.strength * 100).toFixed(1)}%</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

const styles = {
  wrapper: { display: "flex", flexDirection: "column", gap: 18 },

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

  ticker: { fontSize: 34, fontWeight: 800 },
  subtitle: { color: "#64748b" },

  price: { fontSize: 32, fontWeight: 800 },
  priceLabel: { color: "#64748b", fontSize: 12 },

  marketCap: { fontSize: 20, fontWeight: 700 },
  marketCapLabel: { color: "#64748b", fontSize: 12 },

  metricsGrid: {
    display: "flex",
    flexWrap: "wrap",
    gap: 12,
  },

  metricCard: {
    flex: "1 1 160px",
    background: "#0b1020",
    border: "1px solid #172033",
    borderRadius: 14,
    padding: 14,
  },

  metricLabel: {
    fontSize: 11,
    color: "#64748b",
    marginBottom: 8,
  },

  metricValue: {
    fontSize: 20,
    fontWeight: 700,
  },

  section: { display: "flex", flexDirection: "column", gap: 10 },

  sectionTitle: { fontSize: 18, fontWeight: 700 },

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

  chartTitle: { fontSize: 16, fontWeight: 600, marginBottom: 10 },

  tableCard: {
    background: "#0b1020",
    border: "1px solid #172033",
    borderRadius: 18,
    padding: 16,
  },

  table: {
    width: "100%",
    borderCollapse: "collapse",
  },

  zoneRow: {
    display: "flex",
    justifyContent: "space-between",
    padding: "8px 0",
    borderBottom: "1px solid #172033",
  },
};