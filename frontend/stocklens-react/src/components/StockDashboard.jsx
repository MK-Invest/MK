import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  ReferenceLine,
} from "recharts";

import RsiHeatmap from "./RsiHeatmap";

// ─────────────────────────────────────────────
// FORMATTERS
// ─────────────────────────────────────────────

const safe = (v) => v === null || v === undefined || Number.isNaN(v);

const fmtB = (v) => (safe(v) ? "—" : `${(v / 1e9).toFixed(2)} mld. USD`);
const fmtPct = (v) => (safe(v) ? "—" : `${(v * 100).toFixed(2)} %`);
const fmtX = (v) => (safe(v) ? "—" : `${v.toFixed(2)}x`);
const fmtUSD = (v) => (safe(v) ? "—" : `${v.toFixed(2)} USD`);
const fmtDate = (s) => {
  if (!s) return "—";
  const d = new Date(s);
  if (Number.isNaN(d.getTime())) return "—";
  return `${d.getDate().toString().padStart(2, "0")}.${(
    d.getMonth() + 1
  )
    .toString()
    .padStart(2, "0")}.${d.getFullYear()}`;
};

// ─────────────────────────────────────────────
// RSI ENGINE (D/W/M)
// ─────────────────────────────────────────────

function rsiScore(v) {
  if (v == null) return 0;
  if (v < 30) return 100;
  if (v > 70) return 0;
  return 50;
}

function rsiLabel(v) {
  if (v == null) return "—";
  if (v < 30) return "Oversold";
  if (v > 70) return "Overbought";
  return "Neutral";
}

function rsiColor(v) {
  if (v == null) return "#64748B";
  if (v < 30) return "#4ADE80";
  if (v > 70) return "#F87171";
  return "#94A3B8";
}

// ─────────────────────────────────────────────
// TREND ENGINE
// ─────────────────────────────────────────────

function trendAnalysis(rsi) {
  const d = rsi?.D;
  const w = rsi?.W;
  const m = rsi?.M;

  const weights = [
    { v: d, w: 0.5 },
    { v: w, w: 0.3 },
    { v: m, w: 0.2 },
  ];

  let score = 0;
  let total = 0;

  for (const r of weights) {
    if (r.v == null) continue;
    score += rsiScore(r.v) * r.w;
    total += r.w;
  }

  const final = total ? score / total : 0;

  let signal = "Neutral";
  if (final >= 70) signal = "Bullish";
  if (final <= 30) signal = "Bearish";

  return { score: final, signal };
}

// ─────────────────────────────────────────────
// MAIN COMPONENT
// ─────────────────────────────────────────────

export function StockDashboard({ data }) {
  if (!data) return null;

  const f = data.fundamentals || {};
  const m = data.metrics || {};
  const ttm = m.ttm || {};
  const quarters = m.quarters || [];
  const trend = m.trend || {};
  const tech = data.technical || {};
  const zones = tech.zones || {};
  const price = data.price;

  const rsi = tech.rsi || {};
  const trendRsi = trendAnalysis(rsi);

  const h = f.history || {};
  const revH = h.revenue || [];
  const niH = h.net_income || [];
  const opH = h.operating_income || [];

  const histRows = revH.map((r, i) => ({
    end: r?.end,
    revenue: r?.val ?? null,
    net_income: niH[i]?.val ?? null,
    op_income: opH[i]?.val ?? null,
    ebitda:
      opH[i]?.val != null ? opH[i].val : null,
  }));

  return (
    <div style={{ background: "#0A0E1A", color: "#E2E8F0", minHeight: "100vh", padding: 20 }}>

      {/* HEADER */}
      <div style={{ marginBottom: 20 }}>
        <h1>{data.ticker}</h1>
        <div>{price ? `${price.toFixed(2)} USD` : "—"}</div>
      </div>

      {/* RSI + TREND */}
      <section style={{ marginBottom: 30 }}>
        <h2>RSI (D / W / M)</h2>

        {["D", "W", "M"].map((tf) => (
          <div key={tf}>
            <b>{tf}</b>: {rsi?.[tf] ?? "—"}{" "}
            <span style={{ color: rsiColor(rsi?.[tf]) }}>
              ({rsiLabel(rsi?.[tf])})
            </span>
          </div>
        ))}

        {/* TREND SCORE */}
        <div style={{ marginTop: 10 }}>
          <h3>Trend síla</h3>

          <div style={{ background: "#1E293B", height: 10, borderRadius: 6 }}>
            <div
              style={{
                width: `${trendRsi.score}%`,
                height: 10,
                borderRadius: 6,
                background:
                  trendRsi.score > 70
                    ? "#4ADE80"
                    : trendRsi.score < 30
                    ? "#F87171"
                    : "#94A3B8",
              }}
            />
          </div>

          <div>Score: {trendRsi.score.toFixed(1)} / 100</div>

          <div
            style={{
              marginTop: 6,
              padding: 8,
              display: "inline-block",
              borderRadius: 6,
              background:
                trendRsi.signal === "Bullish"
                  ? "#052E16"
                  : trendRsi.signal === "Bearish"
                  ? "#1F0A0A"
                  : "#172033",
              color:
                trendRsi.signal === "Bullish"
                  ? "#4ADE80"
                  : trendRsi.signal === "Bearish"
                  ? "#F87171"
                  : "#94A3B8",
              fontWeight: 700,
            }}
          >
            {trendRsi.signal}
          </div>
        </div>

        {/* HEAT */}
        <div style={{ marginTop: 15, display: "flex", gap: 8 }}>
          {["D", "W", "M"].map((tf) => (
            <div
              key={tf}
              style={{
                flex: 1,
                padding: 10,
                textAlign: "center",
                borderRadius: 6,
                background: rsiColor(rsi?.[tf]),
                color: "#0A0E1A",
                fontWeight: 700,
              }}
            >
              {tf}: {rsi?.[tf] ?? "—"}
            </div>
          ))}
        </div>
      </section>

      {/* ───── SUPPORT / RESISTANCE (VRÁCENO) ───── */}
      <section>
        <h2>Supply / Demand zóny</h2>

        {/* DEMAND */}
        {zones.demand?.length > 0 && (
          <>
            <h3 style={{ color: "#4ADE80" }}>Demand</h3>
            {zones.demand.map((z, i) => (
              <div key={i}>
                {z.zone_low?.toFixed(2)} – {z.zone_high?.toFixed(2)} USD
              </div>
            ))}
          </>
        )}

        {/* SUPPLY */}
        {zones.supply?.length > 0 && (
          <>
            <h3 style={{ color: "#F87171" }}>Supply</h3>
            {zones.supply.map((z, i) => (
              <div key={i}>
                {z.zone_low?.toFixed(2)} – {z.zone_high?.toFixed(2)} USD
              </div>
            ))}
          </>
        )}
      </section>

    </div>
  );
}