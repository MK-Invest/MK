// StockDashboard.jsx
// Kompletní dashboard – nahraď obsahy CompanyHeader.jsx a MetricsGrid.jsx
// Importuj a použij místo nich v Overview.jsx:
//   import { StockDashboard } from "../components/StockDashboard";
//   <StockDashboard data={data} />

import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, ReferenceLine } from "recharts";

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
// PRIMITIVES
// ─────────────────────────────────────────────────────────

const S = {
  page:    { background: "#0A0E1A", minHeight: "100vh", color: "#E2E8F0", fontFamily: "'IBM Plex Mono', 'Courier New', monospace", padding: "0 0 60px" },
  header:  { background: "linear-gradient(135deg,#0F172A 0%,#1E293B 100%)", borderBottom: "1px solid #1E3A5F", padding: "24px 32px", display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 12 },
  ticker:  { fontSize: 36, fontWeight: 700, letterSpacing: "0.08em", color: "#38BDF8" },
  price:   { fontSize: 28, fontWeight: 600, color: "#4ADE80" },
  section: { margin: "0 32px 0", borderBottom: "1px solid #1E293B" },
  sectionTitle: { fontSize: 11, fontWeight: 600, letterSpacing: "0.12em", textTransform: "uppercase", color: "#38BDF8", padding: "20px 0 12px", borderBottom: "1px solid #1E3A5F", marginBottom: 0 },
  table:   { width: "100%", borderCollapse: "collapse" },
  th:      { textAlign: "left", padding: "8px 12px", fontSize: 11, color: "#64748B", fontWeight: 500, letterSpacing: "0.06em", textTransform: "uppercase", borderBottom: "1px solid #1E293B" },
  td:      { padding: "9px 12px", fontSize: 13, borderBottom: "1px solid #0F172A", color: "#CBD5E1" },
  tdLabel: { padding: "9px 12px", fontSize: 13, borderBottom: "1px solid #0F172A", color: "#64748B" },
  pos:     { color: "#4ADE80" },
  neg:     { color: "#F87171" },
  warn:    { color: "#FBBF24" },
  badge:   (c) => ({ display: "inline-block", padding: "2px 8px", borderRadius: 4, fontSize: 12, fontWeight: 600, background: c === "green" ? "#052E16" : c === "red" ? "#1F0A0A" : "#172033", color: c === "green" ? "#4ADE80" : c === "red" ? "#F87171" : "#94A3B8" }),
  grid2:   { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 0 },
  grid3:   { display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 0 },
};

// ─────────────────────────────────────────────────────────
// SECTION WRAPPER
// ─────────────────────────────────────────────────────────

function Section({ title, children }) {
  return (
    <div style={S.section}>
      <div style={S.sectionTitle}>{title}</div>
      <div style={{ paddingBottom: 8 }}>{children}</div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────
// TABLE ROWS
// ─────────────────────────────────────────────────────────

function Row({ label, value, color }) {
  return (
    <tr>
      <td style={S.tdLabel}>{label}</td>
      <td style={{ ...S.td, ...(color ? S[color] : {}) }}>{value}</td>
    </tr>
  );
}

// ─────────────────────────────────────────────────────────
// QUARTERLY BAR CHART
// ─────────────────────────────────────────────────────────

function QChart({ data, dataKey, label, color = "#38BDF8" }) {
  if (!data?.length) return <div style={{ color: "#475569", padding: 12, fontSize: 12 }}>No data</div>;

  const chartData = [...data].reverse().map(q => ({
    date: fmtDate(q.end).slice(0, 5),
    val:  q[dataKey] != null ? +(q[dataKey] / 1e9).toFixed(2) : null,
  }));

  return (
    <div style={{ padding: "12px 0" }}>
      <div style={{ fontSize: 11, color: "#64748B", marginBottom: 6, letterSpacing: "0.06em", textTransform: "uppercase" }}>{label} (mld. USD)</div>
      <ResponsiveContainer width="100%" height={140}>
        <BarChart data={chartData} margin={{ top: 4, right: 8, left: -20, bottom: 0 }}>
          <CartesianGrid stroke="#1E293B" strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="date" tick={{ fill: "#64748B", fontSize: 10 }} axisLine={false} tickLine={false} />
          <YAxis tick={{ fill: "#64748B", fontSize: 10 }} axisLine={false} tickLine={false} />
          <ReferenceLine y={0} stroke="#334155" />
          <Tooltip
            contentStyle={{ background: "#0F172A", border: "1px solid #1E3A5F", borderRadius: 6, fontSize: 12 }}
            labelStyle={{ color: "#94A3B8" }}
            itemStyle={{ color }}
            formatter={v => [`${v} mld.`, label]}
          />
          <Bar dataKey="val" fill={color} radius={[3, 3, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

// ─────────────────────────────────────────────────────────
// TREND SIGNAL ROW
// ─────────────────────────────────────────────────────────

function TrendRow({ label, value, note }) {
  const ok = value === true;
  const bad = value === false;
  return (
    <tr>
      <td style={S.tdLabel}>{label}</td>
      <td style={{ ...S.td, ...(ok ? S.pos : bad ? S.neg : {}) }}>
        {ok ? "✅" : bad ? "❌" : "—"} {note || ""}
      </td>
    </tr>
  );
}

// ─────────────────────────────────────────────────────────
// MAIN DASHBOARD
// ─────────────────────────────────────────────────────────

export function StockDashboard({ data }) {
  if (!data) return null;

  const f  = data.fundamentals ?? {};
  const m  = data.metrics ?? {};
  const ttm = m.ttm ?? {};
  const quarters = m.quarters ?? [];
  const trend = m.trend ?? {};
  const tech = data.technical ?? {};
  const zones = tech.zones ?? {};
  const price = data.price;

  // History pro kvartální tabulku (z fundamentals.history)
  const h = f.history ?? {};
  const revH  = h.revenue         ?? [];
  const niH   = h.net_income      ?? [];
  const opH   = h.operating_income ?? [];
  const depH  = h.depreciation    ?? [];

  // Normalizuj historii do řádků podle revenue
  const histRows = revH.map((r, i) => ({
    end:       r.end,
    revenue:   r.val,
    net_income: niH[i]?.val ?? null,
    op_income:  opH[i]?.val ?? null,
    dep:        depH[i]?.val ?? null,
    ebitda:     (opH[i]?.val != null && depH[i]?.val != null) ? opH[i].val + depH[i].val : null,
  }));

  return (
    <div style={S.page}>

      {/* ── HEADER ── */}
      <div style={S.header}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 20 }}>
          <span style={S.ticker}>{data.ticker}</span>
          <span style={S.price}>{price != null ? `${price.toFixed(2)} USD` : "cena nedostupná"}</span>
        </div>
        <div style={{ fontSize: 12, color: "#475569", letterSpacing: "0.04em" }}>
          StockLens · SEC EDGAR · {new Date().toLocaleDateString("cs-CZ")}
        </div>
      </div>

      <div style={{ padding: "0 0" }}>

        {/* ── ZÁKLADNÍ ÚDAJE ── */}
        <Section title="Základní údaje">
          <div style={S.grid2}>
            <table style={S.table}>
              <tbody>
                <Row label="Ticker"                    value={data.ticker} />
                <Row label="Aktuální cena"             value={fmtUSD(price)} />
                <Row label="Počet akcií"               value={fmtShares(f.shares)} />
                <Row label="Tržní kapitalizace"        value={fmtB(ttm.market_cap)} />
                <Row label="Enterprise Value (EV)"     value={fmtB(ttm.ev)} />
              </tbody>
            </table>
            <table style={S.table}>
              <tbody>
                <Row label="Vlastní kapitál"           value={fmtB(f.equity)} />
                <Row label="Celková aktiva"            value={fmtB(f.total_assets)} />
                <Row label="Hotovost"                  value={fmtB(f.cash)} />
                <Row label="Dluh"                      value={fmtB(f.debt)} />
                <Row label="Čistý dluh (Net Debt)"     value={fmtB(ttm.net_debt ?? f.net_debt)} />
              </tbody>
            </table>
          </div>
        </Section>

        {/* ── TTM ── */}
        <Section title="TTM (posledních 12 měsíců)">
          <div style={S.grid2}>
            <table style={S.table}>
              <tbody>
                <Row label="Tržby"                     value={fmtB(f.revenue)} />
                <Row label="Čistý zisk"                value={fmtB(f.net_income)} />
                <Row label="EBITDA"                    value={fmtB(ttm.ebitda ?? f.ebitda)} />
                <Row label="EBITDA marže"              value={fmtPct(f.ebitda_margin)} />
                <Row label="Free Cash Flow"            value={fmtB(f.fcf)} />
                <Row label="EPS (TTM)"                 value={ttm.eps_ttm ? `${ttm.eps_ttm.toFixed(2)} USD` : "—"} />
                <Row label="Dividend na akcii"         value={f.dps ? `${f.dps.toFixed(2)} USD` : "—"} />
              </tbody>
            </table>
            <table style={S.table}>
              <tbody>
                <Row label="P/E"                       value={fmtX(ttm.pe)} />
                <Row label="P/S"                       value={fmtX(ttm.ps)} />
                <Row label="P/B"                       value={fmtX(ttm.pb)} />
                <Row label="EV/EBITDA"                 value={fmtX(ttm.ev_ebitda)} />
                <Row label="EV/FCF"                    value={fmtX(ttm.ev_fcf)} />
                <Row label="FCF Yield"                 value={fmtPct(ttm.fcf_yield)} />
                <Row label="Dividendový výnos"         value={fmtPct(ttm.dividend_yield)} />
                <Row label="ROE"                       value={fmtPct(ttm.roe)} />
                <Row label="ROA"                       value={fmtPct(ttm.roa)} />
                <Row label="Current Ratio"             value={ttm.current_ratio?.toFixed(2) ?? "—"} />
              </tbody>
            </table>
          </div>
        </Section>

        {/* ── KVARTÁLNÍ GRAFY ── */}
        <Section title="Vývoj kvartálních výsledků — grafy">
          <div style={S.grid3}>
            <QChart data={histRows} dataKey="revenue"   label="Tržby"       color="#38BDF8" />
            <QChart data={histRows} dataKey="net_income" label="Čistý zisk"  color="#4ADE80" />
            <QChart data={histRows} dataKey="ebitda"    label="EBITDA"      color="#FBBF24" />
          </div>
        </Section>

        {/* ── KVARTÁLNÍ TABULKA ── */}
        <Section title="Vývoj kvartálních výsledků — tabulka">
          <table style={S.table}>
            <thead>
              <tr>
                <th style={S.th}>Datum</th>
                <th style={S.th}>Tržby</th>
                <th style={S.th}>Čistý zisk</th>
                <th style={S.th}>Provozní zisk</th>
                <th style={S.th}>EBITDA</th>
              </tr>
            </thead>
            <tbody>
              {histRows.map((r, i) => (
                <tr key={i}>
                  <td style={S.tdLabel}>{fmtDate(r.end)}</td>
                  <td style={S.td}>{fmtB(r.revenue)}</td>
                  <td style={{ ...S.td, ...(r.net_income < 0 ? S.neg : {}) }}>{fmtB(r.net_income)}</td>
                  <td style={{ ...S.td, ...(r.op_income < 0 ? S.neg : {}) }}>{fmtB(r.op_income)}</td>
                  <td style={S.td}>{fmtB(r.ebitda)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>

        {/* ── ODPISY ── */}
        <Section title="Odpisy (Depreciation & Amortization)">
          <table style={S.table}>
            <thead>
              <tr>
                <th style={S.th}>Datum</th>
                <th style={S.th}>Hodnota</th>
              </tr>
            </thead>
            <tbody>
              {depH.map((r, i) => (
                <tr key={i}>
                  <td style={S.tdLabel}>{fmtDate(r.end)}</td>
                  <td style={S.td}>{fmtB(r.val)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>

        {/* ── VALUACE PO KVARTÁLECH ── */}
        <Section title="Valuace po jednotlivých kvartálech">
          <table style={S.table}>
            <thead>
              <tr>
                <th style={S.th}>Datum</th>
                <th style={S.th}>P/E</th>
                <th style={S.th}>EV/EBITDA</th>
                <th style={S.th}>P/S</th>
                <th style={S.th}>EPS</th>
              </tr>
            </thead>
            <tbody>
              {quarters.map((q, i) => {
                const extreme = q.pe != null && q.pe > 200;
                return (
                  <tr key={i}>
                    <td style={S.tdLabel}>{fmtDate(q.end)}</td>
                    <td style={{ ...S.td, ...(extreme ? S.warn : {}) }}>
                      {q.pe != null ? q.pe.toFixed(2) : "—"}
                      {extreme && <span style={{ fontSize: 10, color: "#94A3B8", marginLeft: 4 }}>⚠</span>}
                    </td>
                    <td style={S.td}>{q.ev_ebitda != null ? q.ev_ebitda.toFixed(2) : "—"}</td>
                    <td style={S.td}>{q.ps != null ? q.ps.toFixed(2) : "—"}</td>
                    <td style={S.td}>{q.eps != null ? `${q.eps.toFixed(3)} USD` : "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {quarters.some(q => q.pe > 200) && (
            <div style={{ fontSize: 11, color: "#64748B", padding: "6px 12px" }}>
              ⚠ Extrémní P/E vzniká při téměř nulovém čistém zisku — neodráží skutečnou valuaci.
            </div>
          )}
        </Section>

        {/* ── FINANČNÍ ZDRAVÍ ── */}
        <Section title="Finanční zdraví">
          <table style={S.table}>
            <thead>
              <tr>
                <th style={S.th}>Ukazatel</th>
                <th style={S.th}>Vyhodnocení</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td style={S.tdLabel}>Likvidita</td>
                <td style={S.td}>
                  <span style={S.badge(ttm.current_ratio >= 1.5 ? "green" : ttm.current_ratio >= 1 ? "neutral" : "red")}>
                    {ttm.current_ratio >= 1.5 ? "Dobrá" : ttm.current_ratio >= 1 ? "Přijatelná" : "Slabá"}
                  </span>
                  {" "}(Current Ratio {ttm.current_ratio?.toFixed(2)})
                </td>
              </tr>
              <tr>
                <td style={S.tdLabel}>Free Cash Flow</td>
                <td style={S.td}>
                  <span style={S.badge(f.fcf > 0 ? "green" : "red")}>
                    {f.fcf > 0 ? "Pozitivní" : "Negativní"}
                  </span>
                  {" "}{fmtB(f.fcf)}
                </td>
              </tr>
              <tr>
                <td style={S.tdLabel}>Dividendy</td>
                <td style={S.td}>
                  <span style={S.badge(f.dps > 0 ? "green" : "neutral")}>
                    {f.dps > 0 ? "Vypláceny" : "Nevypláceny"}
                  </span>
                </td>
              </tr>
              <tr>
                <td style={S.tdLabel}>Dividendový výnos</td>
                <td style={{ ...S.td, ...(ttm.dividend_yield > 0.05 ? S.pos : {}) }}>
                  {fmtPct(ttm.dividend_yield)}
                  {ttm.dividend_yield > 0.05 && " — velmi vysoký"}
                </td>
              </tr>
              <tr>
                <td style={S.tdLabel}>ROE</td>
                <td style={{ ...S.td, ...(ttm.roe >= 0.15 ? S.pos : ttm.roe >= 0.08 ? {} : S.neg) }}>
                  {fmtPct(ttm.roe)}
                  {" — "}{ttm.roe >= 0.15 ? "nadprůměrné" : ttm.roe >= 0.08 ? "průměrné" : "podprůměrné"}
                </td>
              </tr>
              <tr>
                <td style={S.tdLabel}>Čistý dluh</td>
                <td style={S.td}>{fmtB(ttm.net_debt ?? f.net_debt)}</td>
              </tr>
              <tr>
                <td style={S.tdLabel}>Obrat pracovního kapitálu</td>
                <td style={S.td}>{fmtB(f.operating_working_capital)}</td>
              </tr>
            </tbody>
          </table>
        </Section>

        {/* ── TRENDOVÉ SIGNÁLY ── */}
        <Section title="Trendové signály">
          <table style={S.table}>
            <thead>
              <tr>
                <th style={S.th}>Faktor</th>
                <th style={S.th}>Stav</th>
              </tr>
            </thead>
            <tbody>
              <TrendRow label="Růst tržeb (QoQ)"       value={trend.revenue_up}         note={trend.revenue_growth != null ? `${(trend.revenue_growth * 100).toFixed(1)} %` : ""} />
              <TrendRow label="FCF pozitivní"           value={trend.fcf_positive} />
              <TrendRow label="FCF silné (yield >5 %)" value={trend.fcf_strong} />
              <TrendRow label="EPS roste"               value={trend.eps_growing} />
              <TrendRow label="ROE nadprůměrné (>15 %)" value={trend.roe_good} />
              <TrendRow label="ROIC elite (>20 %)"     value={trend.roic_elite} />
              <TrendRow label="Vyplácí dividendu"       value={trend.pays_dividend} />
              <TrendRow label="Vysoký dividendový výnos" value={trend.high_yield_dividend} />
              <TrendRow label="Likvidita dostatečná"    value={trend.liquid} />
              <TrendRow label="Nízké zadlužení (D/E <0.5)" value={trend.low_debt} />
            </tbody>
          </table>
        </Section>

        {/* ── TECHNICKÁ ANALÝZA ── */}
        {tech.rsi != null && (
          <Section title="Technická analýza">
            <div style={S.grid2}>
              <table style={S.table}>
                <tbody>
                  <Row label="RSI (14)"        value={tech.rsi?.toFixed(2)} color={tech.rsi < 30 ? "pos" : tech.rsi > 70 ? "neg" : null} />
                  <Row label="RSI signál"      value={
                    tech.rsi_signal === "oversold"   ? "🟢 Přeprodáno" :
                    tech.rsi_signal === "overbought" ? "🔴 Překoupeno" :
                    "⚪ Neutrální"
                  } />
                  <Row label="EMA 20"          value={fmtUSD(tech.ema_20)} />
                  <Row label="SMA 50"          value={fmtUSD(tech.sma_50)} />
                  <Row label="SMA 200"         value={fmtUSD(tech.sma_200)} />
                </tbody>
              </table>
              <table style={S.table}>
                <tbody>
                  <Row label="Cena nad EMA20"  value={tech.above_ema20  ? "✅ Ano" : "❌ Ne"} color={tech.above_ema20  ? "pos" : "neg"} />
                  <Row label="Cena nad SMA50"  value={tech.above_sma50  ? "✅ Ano" : "❌ Ne"} color={tech.above_sma50  ? "pos" : "neg"} />
                  <Row label="Cena nad SMA200" value={tech.above_sma200 ? "✅ Ano" : "❌ Ne"} color={tech.above_sma200 ? "pos" : "neg"} />
                  <Row label="Celkový trend"   value={
                    tech.trend === "bullish" ? "🟢 Mírně býčí" :
                    tech.trend === "bearish" ? "🔴 Medvědí" :
                    "⚪ Neutrální"
                  } />
                  <Row label="Počet svíček"    value={tech.candle_count} />
                </tbody>
              </table>
            </div>

            {/* Support zóny */}
            {zones.demand?.length > 0 && (
              <div style={{ marginTop: 16 }}>
                <div style={{ fontSize: 11, color: "#4ADE80", letterSpacing: "0.08em", textTransform: "uppercase", padding: "8px 12px 4px", fontWeight: 600 }}>
                  ▼ Klíčové supporty (poptávkové zóny)
                </div>
                <table style={S.table}>
                  <thead>
                    <tr>
                      <th style={S.th}>Cena</th>
                      <th style={S.th}>Síla</th>
                      <th style={S.th}>Počet dotyků</th>
                      <th style={S.th}>Datum(y) dotyku</th>
                    </tr>
                  </thead>
                  <tbody>
                    {zones.demand.map((z, i) => (
                      <tr key={i}>
                        <td style={{ ...S.td, ...S.pos }}>{z.price.toFixed(2)} USD</td>
                        <td style={S.td}>{(z.strength * 100).toFixed(1)} %</td>
                        <td style={S.td}>{z.touch_count}×</td>
                        <td style={{ ...S.td, fontSize: 12, color: "#64748B" }}>{z.dates.join(", ")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {/* Resistance zóny */}
            {zones.supply?.length > 0 && (
              <div style={{ marginTop: 8 }}>
                <div style={{ fontSize: 11, color: "#F87171", letterSpacing: "0.08em", textTransform: "uppercase", padding: "8px 12px 4px", fontWeight: 600 }}>
                  ▲ Klíčové rezistence (nabídkové zóny)
                </div>
                <table style={S.table}>
                  <thead>
                    <tr>
                      <th style={S.th}>Cena</th>
                      <th style={S.th}>Síla</th>
                      <th style={S.th}>Počet dotyků</th>
                      <th style={S.th}>Datum(y) dotyku</th>
                    </tr>
                  </thead>
                  <tbody>
                    {zones.supply.map((z, i) => (
                      <tr key={i}>
                        <td style={{ ...S.td, ...S.neg }}>{z.price.toFixed(2)} USD</td>
                        <td style={S.td}>{(z.strength * 100).toFixed(1)} %</td>
                        <td style={S.td}>{z.touch_count}×</td>
                        <td style={{ ...S.td, fontSize: 12, color: "#64748B" }}>{z.dates.join(", ")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Section>
        )}

      </div>
    </div>
  );
}
