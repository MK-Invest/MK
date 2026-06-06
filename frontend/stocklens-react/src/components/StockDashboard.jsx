// StockDashboard.jsx

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  ReferenceLine
} from "recharts";

import RsiHeatmap from "./RsiHeatmap";

// ─────────────────────────────────────────────────────────
// FORMATTERS
// ─────────────────────────────────────────────────────────

const fmtB   = v => v == null ? "—" : `${(v / 1e9).toFixed(2)} mld. USD`;
const fmtM   = v => v == null ? "—" : `${(v / 1e6).toFixed(0)} mil. USD`;
const fmtPct = v => v == null ? "—" : `${(v * 100).toFixed(2)} %`;
const fmtX   = v => v == null ? "—" : `${v.toFixed(2)}x`;
const fmtUSD = v => v == null ? "—" : `${v.toFixed(2)} USD`;
const fmtShares = v => v == null ? "—" : `${(v / 1e9).toFixed(3)} mld.`;
const fmtDate = s => {
  if (!s) return "—";
  const d = new Date(s);
  return `${d.getDate().toString().padStart(2,"0")}.${(d.getMonth()+1).toString().padStart(2,"0")}.${d.getFullYear()}`;
};

// ─────────────────────────────────────────────────────────
// STYLES
// ─────────────────────────────────────────────────────────

const S = {
  page: { background: "#0A0E1A", minHeight: "100vh", color: "#E2E8F0", fontFamily: "'IBM Plex Mono', monospace", padding: "0 0 60px" },
  header: { background: "linear-gradient(135deg,#0F172A,#1E293B)", borderBottom: "1px solid #1E3A5F", padding: "24px 32px", display: "flex", justifyContent: "space-between" },
  ticker: { fontSize: 36, color: "#38BDF8", fontWeight: 700 },
  price: { fontSize: 28, color: "#4ADE80" },
  section: { margin: "0 32px", borderBottom: "1px solid #1E293B" },
  sectionTitle: { fontSize: 11, color: "#38BDF8", textTransform: "uppercase", padding: "20px 0 10px" },
  table: { width: "100%", borderCollapse: "collapse" },
  td: { padding: 8, color: "#CBD5E1", borderBottom: "1px solid #0F172A" },
  tdLabel: { padding: 8, color: "#64748B", borderBottom: "1px solid #0F172A" },
  pos: { color: "#4ADE80" },
  neg: { color: "#F87171" },
};

// ─────────────────────────────────────────────────────────

function Section({ title, children }) {
  return (
    <div style={S.section}>
      <div style={S.sectionTitle}>{title}</div>
      {children}
    </div>
  );
}

function Row({ label, value, color }) {
  return (
    <tr>
      <td style={S.tdLabel}>{label}</td>
      <td style={{ ...S.td, ...(color ? S[color] : {}) }}>{value}</td>
    </tr>
  );
}

// ─────────────────────────────────────────────────────────

export function StockDashboard({ data }) {
  if (!data) return null;

  const f = data.fundamentals ?? {};
  const m = data.metrics ?? {};
  const ttm = m.ttm ?? {};
  const quarters = m.quarters ?? [];
  const trend = m.trend ?? {};
  const tech = data.technical ?? {};
  const zones = tech.zones ?? {};
  const price = data.price;

  const h = f.history ?? {};
  const revH = h.revenue ?? [];
  const niH = h.net_income ?? [];
  const opH = h.operating_income ?? [];

  const histRows = revH.map((r, i) => ({
    end: r.end,
    revenue: r.val,
    net_income: niH[i]?.val ?? null,
    op_income: opH[i]?.val ?? null,
    ebitda: (opH[i]?.val ?? 0)
  }));

  return (
    <div style={S.page}>

      {/* HEADER */}
      <div style={S.header}>
        <div>
          <div style={S.ticker}>{data.ticker}</div>
          <div style={S.price}>{price ? `${price.toFixed(2)} USD` : "—"}</div>
        </div>
      </div>

      {/* BASIC */}
      <Section title="Základní údaje">
        <table style={S.table}>
          <tbody>
            <Row label="Ticker" value={data.ticker} />
            <Row label="Cena" value={fmtUSD(price)} />
            <Row label="Akcie" value={fmtShares(f.shares)} />
          </tbody>
        </table>
      </Section>

      {/* TECHNICAL - FIXED JSX */}
      {tech.rsi && (
        <Section title="Technická analýza">

          <RsiHeatmap rsi={tech.rsi} />

          <table style={S.table}>
            <tbody>
              <Row
                label="RSI D"
                value={
                  tech.rsi.D > 70 ? "🔴 Overbought" :
                  tech.rsi.D < 30 ? "🟢 Oversold" :
                  "⚪ Neutral"
                }
              />
              <Row label="EMA20" value={fmtUSD(tech.ema_20)} />
              <Row label="SMA50" value={fmtUSD(tech.sma_50)} />
              <Row label="SMA200" value={fmtUSD(tech.sma_200)} />

              <Row label="Trend" value={tech.trend} />
              <Row label="Počet svíček" value={tech.candle_count} />
            </tbody>
          </table>

          {/* ZÓNY JSOU UVNITŘ SECTION - FIX JSX */}
          {zones.demand?.length > 0 && (
            <>
              <div style={{ color: "#4ADE80", fontSize: 11, marginTop: 12 }}>
                Demand zóny
              </div>
              <table style={S.table}>
                <tbody>
                  {zones.demand.map((z, i) => (
                    <tr key={i}>
                      <td style={S.td}>{z.zone_low} – {z.zone_high}</td>
                      <td style={S.td}>{z.zone_mid}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}

          {zones.supply?.length > 0 && (
            <>
              <div style={{ color: "#F87171", fontSize: 11, marginTop: 12 }}>
                Supply zóny
              </div>
              <table style={S.table}>
                <tbody>
                  {zones.supply.map((z, i) => (
                    <tr key={i}>
                      <td style={S.td}>{z.zone_low} – {z.zone_high}</td>
                      <td style={S.td}>{z.zone_mid}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}

        </Section>
      )}

    </div>
  );
}