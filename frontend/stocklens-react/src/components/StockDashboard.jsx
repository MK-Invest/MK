import { useState } from "react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, ReferenceLine } from "recharts";

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
// Převede ISO datum konce kvartálu ("2026-03-29") na "Q1 '26"
const fmtQuarter = s => {
  if (!s) return "—";
  const d = new Date(s);
  const quarter = Math.ceil((d.getMonth() + 1) / 3);
  const shortYear = d.getFullYear().toString().slice(2);
  return `Q${quarter} '${shortYear}`;
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

function QChart({ data, dataKey, label, color = "#38BDF8", unit = "B" }) {
  if (!data?.length) return <div style={{ color: "#475569", padding: 12, fontSize: 12 }}>No data</div>;

  // unit řídí škálování i formát tooltipu:
  //   "B" — miliardy USD (revenue, net income, EBITDA)
  //   "x" — násobek beze škálování (P/E, P/S)
  //   "$" — dolary beze škálování (EPS)
  const scale = unit === "B" ? 1e9 : 1;
  const suffix = unit === "B" ? " mld." : unit === "x" ? "x" : " USD";
  const unitLabel = unit === "B" ? "(mld. USD)" : unit === "x" ? "(násobek)" : "(USD)";

  const chartData = [...data].reverse().map(q => ({
    date: fmtQuarter(q.end),
    val:  q[dataKey] != null ? +(q[dataKey] / scale).toFixed(2) : null,
  }));

  return (
    <div style={{ padding: "12px 0" }}>
      <div style={{ fontSize: 11, color: "#64748B", marginBottom: 6, letterSpacing: "0.06em", textTransform: "uppercase" }}>{label} {unitLabel}</div>
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
            formatter={v => [`${v}${suffix}`, label]}
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


// ─────────────────────────────────────────────────────────
// VLASTNÍ RŮSTOVÉ PŘEDPOKLADY — bear/base/bull revenue_cagr
// ─────────────────────────────────────────────────────────

function GrowthInputsForm({ scenarios, onRecalculate, recalculating }) {
  // Předvyplň aktuálními hodnotami (auto-odhad nebo dříve zadané),
  // ať uživatel vidí od čeho vychází, ne prázdná pole.
  //
  // Pokud auto-odhad vyjde záporný (typicky firma po restrukturalizaci/
  // spin-offu, kde 5Y historie obsahuje starý pokles — viz MMM/3M),
  // záporné číslo v poli matoucně vypadá jako "model predikuje propad",
  // i když jde jen o zašuměnou historii. Místo toho předvyplníme
  // konzervativní kladné defaulty (2/4/6 %), které si uživatel může
  // libovolně upravit — lepší startovní bod než matoucí záporná čísla.
  const NEGATIVE_FALLBACK = { bear: 2, base: 4, bull: 6 };

  const hasNegativeAutoEstimate = ["bear", "base", "bull"].some(
    (key) => (scenarios?.[key]?.revenue_cagr ?? 0) < 0
  );

  const initial = (key) => {
    if (hasNegativeAutoEstimate) {
      return NEGATIVE_FALLBACK[key].toFixed(1);
    }
    const v = scenarios?.[key]?.revenue_cagr;
    return v != null ? (v * 100).toFixed(1) : "";
  };

  const [bear, setBear] = useState(initial("bear"));
  const [base, setBase] = useState(initial("base"));
  const [bull, setBull] = useState(initial("bull"));

  const parsePct = (s) => {
    const n = parseFloat(String(s).replace(",", "."));
    return Number.isFinite(n) ? n / 100 : null;
  };

  const handleCalculate = () => {
    const overrides = {};
    const b = parsePct(bear);
    const ba = parsePct(base);
    const bu = parsePct(bull);

    if (b !== null) overrides.bear = { revenue_cagr: b };
    if (ba !== null) overrides.base = { revenue_cagr: ba };
    if (bu !== null) overrides.bull = { revenue_cagr: bu };

    onRecalculate(overrides);
  };

  const inputStyle = {
    width: 90,
    padding: "6px 8px",
    background: "#0F172A",
    border: "1px solid #1E3A5F",
    borderRadius: 6,
    color: "#E2E8F0",
    fontSize: 13,
    fontFamily: "inherit",
    outline: "none",
  };

  const labelStyle = {
    fontSize: 11,
    color: "#64748B",
    letterSpacing: "0.06em",
    textTransform: "uppercase",
    marginBottom: 4,
    display: "block",
  };

  return (
    <div style={{
      display: "flex",
      alignItems: "flex-end",
      gap: 16,
      padding: "12px 12px 16px",
      flexWrap: "wrap",
    }}>
      <div>
        <label style={labelStyle}>Bear růst (%)</label>
        <input
          style={inputStyle}
          type="text"
          inputMode="decimal"
          value={bear}
          onChange={(e) => setBear(e.target.value)}
          placeholder="např. 7"
        />
      </div>
      <div>
        <label style={labelStyle}>Base růst (%)</label>
        <input
          style={inputStyle}
          type="text"
          inputMode="decimal"
          value={base}
          onChange={(e) => setBase(e.target.value)}
          placeholder="např. 10"
        />
      </div>
      <div>
        <label style={labelStyle}>Bull růst (%)</label>
        <input
          style={inputStyle}
          type="text"
          inputMode="decimal"
          value={bull}
          onChange={(e) => setBull(e.target.value)}
          placeholder="např. 15"
        />
      </div>
      <button
        onClick={handleCalculate}
        disabled={recalculating}
        style={{
          padding: "8px 18px",
          background: recalculating ? "#1E293B" : "#1E3A5F",
          border: "1px solid #2563EB",
          borderRadius: 6,
          color: recalculating ? "#64748B" : "#38BDF8",
          fontSize: 13,
          fontFamily: "inherit",
          cursor: recalculating ? "default" : "pointer",
          whiteSpace: "nowrap",
        }}
      >
        {recalculating ? "⟳ Počítám..." : "Calculate"}
      </button>
      <div style={{ fontSize: 11, color: "#475569", maxWidth: 280 }}>
        Roční růst tržeb, který očekáváš pro daný scénář. Použije se konzistentně
        pro EV/EBITDA i DCF model. Prázdné pole = automatický odhad z historie.
      </div>
      {hasNegativeAutoEstimate && (
        <div style={{ fontSize: 11, color: "#FBBF24", maxWidth: 280 }}>
          ⚠ Automatický odhad z historie vyšel záporný (firma pravděpodobně
          prošla restrukturalizací nebo spin-offem, který zkresluje 5Y data) —
          předvyplnili jsme konzervativní 2/4/6 %. Uprav podle vlastního úsudku.
        </div>
      )}
    </div>
  );
}

function ValuationModelsTable({ scenarios, price, onRecalculate, recalculating }) {
  if (!scenarios?.base) {
    return <div style={{ color: "#475569", padding: 12, fontSize: 12 }}>Valuation models not loaded</div>;
  }

  const modelRows = [
    { key: "composite", label: "Composite" },
    { key: "ev_ebitda", label: "EV/EBITDA" },
    { key: "dcf_short", label: "DCF (3Y, exit multiple)" },
    { key: "dcf", label: "DCF" },
    { key: "dcf_normalized", label: "DCF (3Y median)" },
    { key: "fcf_yield", label: "FCF Yield" },
    { key: "roic_ep", label: "ROIC / EP" },
  ];
  const scenarioKeys = ["bear", "base", "bull"];

  const modelPrice = (scenario, key) => {
    const sc = scenarios?.[scenario];
    if (!sc) return null;
    if (key === "composite") return sc.composite?.price ?? sc.price ?? null;
    return sc.models?.[key]?.price ?? null;
  };

  const modelConfidence = (scenario, key) => {
    const sc = scenarios?.[scenario];
    if (!sc) return null;
    if (key === "composite") return sc.composite?.confidence ?? null;
    return sc.models?.[key]?.confidence ?? null;
  };

  const cellStyle = (value) => ({
    ...S.td,
    ...(value != null && price ? (value >= price ? S.pos : S.neg) : {}),
  });

  return (
    <>
      {onRecalculate && (
        <GrowthInputsForm
          scenarios={scenarios}
          onRecalculate={onRecalculate}
          recalculating={recalculating}
        />
      )}
      <table style={S.table}>
        <thead>
          <tr>
            <th style={S.th}>Model</th>
            <th style={S.th}>Bear</th>
            <th style={S.th}>Base</th>
            <th style={S.th}>Bull</th>
            <th style={S.th}>Base confidence</th>
          </tr>
        </thead>
        <tbody>
          {modelRows.map(row => {
            const baseVal = modelPrice("base", row.key);
            return (
              <tr key={row.key}>
                <td style={S.tdLabel}>{row.label}</td>
                {scenarioKeys.map(key => {
                  const value = modelPrice(key, row.key);
                  return <td key={key} style={cellStyle(value)}>{fmtUSD(value)}</td>;
                })}
                <td style={S.td}>{fmtPct(modelConfidence("base", row.key))}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <div style={{ fontSize: 11, color: "#64748B", padding: "8px 12px" }}>
        Hodnoty jsou price targety na akcii. Zelena znamena nad aktualni cenou, cervena pod aktualni cenou.
      </div>
      {scenarios.base?.models?.dcf && (
        <div style={{ fontSize: 11, color: "#64748B", padding: "0 12px 10px" }}>
          Base DCF inputs: FCF <strong style={{ color: "#CBD5E1" }}>{fmtB(scenarios.base.models.dcf.fcf)}</strong>, WACC <strong style={{ color: "#CBD5E1" }}>{fmtPct(scenarios.base.models.dcf.wacc)}</strong>, FCF growth <strong style={{ color: "#CBD5E1" }}>{fmtPct(scenarios.base.models.dcf.fcf_growth)}</strong>, terminal growth <strong style={{ color: "#CBD5E1" }}>{fmtPct(scenarios.base.models.dcf.terminal_growth)}</strong>, years <strong style={{ color: "#CBD5E1" }}>{scenarios.base.models.dcf.years}</strong>.
        </div>
      )}
    </>
  );
}

// ─────────────────────────────────────────────────────────
// MAIN DASHBOARD
// ─────────────────────────────────────────────────────────

export function StockDashboard({ data, onRecalculate, recalculating }) {
  if (!data) return null;

  const f  = data.fundamentals ?? {};
  const m  = data.metrics ?? {};
  const ttm = m.ttm ?? {};
  const quarters = m.quarters ?? [];
  const trend = m.trend ?? {};
  const tech = data.technical ?? {};
  const zones = tech.zones ?? {};
  const price = data.price;
  const scenarios = data.scenarios ?? {};
  const valuationHistorical = data.valuationHistorical ?? {};

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

  // Doplň P/E, P/S, EPS z metrics.quarters (jiný zdroj, stejné 'end' datum)
  // do stejných řádků jako revenue/net_income/ebitda, ať grafy čerpají
  // z jediného sloučeného pole.
  const quartersByEnd = Object.fromEntries(quarters.map(q => [q.end, q]));
  const chartRows = histRows.map(r => ({
    ...r,
    pe:  quartersByEnd[r.end]?.pe  ?? null,
    ps:  quartersByEnd[r.end]?.ps  ?? null,
    eps: quartersByEnd[r.end]?.eps ?? null,
  }));

  return (
    <div style={S.page}>

      {/* ── HEADER ── */}
      <div style={S.header}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 20, flexWrap: "wrap" }}>
          <span style={S.ticker}>{data.ticker}</span>
          {data.name && data.name !== data.ticker && (
            <span style={{ fontSize: 16, color: "#94A3B8", fontWeight: 400 }}>{data.name}</span>
          )}
          <span style={S.price}>{price != null ? `${price.toFixed(2)} USD` : "cena nedostupná"}</span>
        </div>
        <div style={{ fontSize: 12, color: "#475569", letterSpacing: "0.04em" }}>
          StockLens · {new Date().toLocaleDateString("cs-CZ")}
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
                <Section title="Valuation models">
          <div style={S.grid2}>
            <table style={S.table}>
              <tbody>
                <Row label="Rating" value={data.valuationRating ?? "-"} color={data.valuationRatingColor === "green" ? "pos" : data.valuationRatingColor === "red" ? "neg" : "warn"} />
                <Row label="Required return" value={fmtPct(data.valuationRequiredReturn)} />
                <Row label="Horizon" value={data.valuationYears ? `${data.valuationYears} roky` : "-"} />
                <Row label="Hist. revenue CAGR" value={fmtPct(valuationHistorical.hist_cagr)} />
                <Row label="Hist. EPS CAGR (2Y)" value={fmtPct(f.eps_cagr_2y)} />
                <Row label="Hist. FCF CAGR (2Y)" value={fmtPct(f.fcf_cagr_2y)} />
              </tbody>
            </table>
            <table style={S.table}>
              <tbody>
                <Row label="Base intrinsic value" value={fmtUSD(scenarios.base?.intrinsic_value)} color={scenarios.base?.upside >= 0 ? "pos" : "neg"} />
                <Row label="Base upside" value={fmtPct(scenarios.base?.upside)} color={scenarios.base?.upside >= 0 ? "pos" : "neg"} />
                <Row label="Base revenue CAGR" value={fmtPct(scenarios.base?.revenue_cagr)} />
                <Row label="Base EBITDA margin" value={fmtPct(scenarios.base?.ebitda_margin)} />
              </tbody>
            </table>
          </div>
          <ValuationModelsTable
            scenarios={scenarios}
            price={price}
            onRecalculate={onRecalculate}
            recalculating={recalculating}
          />
        </Section>

<Section title="Vývoj kvartálních výsledků — grafy">
          <div style={S.grid3}>
            <QChart data={chartRows} dataKey="revenue"    label="Tržby"       color="#38BDF8" unit="B" />
            <QChart data={chartRows} dataKey="net_income" label="Čistý zisk"  color="#4ADE80" unit="B" />
            <QChart data={chartRows} dataKey="ebitda"     label="EBITDA"      color="#FBBF24" unit="B" />
            <QChart data={chartRows} dataKey="pe"         label="P/E"         color="#A78BFA" unit="x" />
            <QChart data={chartRows} dataKey="ps"         label="P/S"         color="#F472B6" unit="x" />
            <QChart data={chartRows} dataKey="eps"        label="EPS"         color="#34D399" unit="$" />
          </div>
        </Section>

        {/* ── TECHNICKÁ ANALÝZA ── */}
       <Section title="Technická analýza">

  <RsiHeatmap rsi={tech.rsi} />

  <table style={S.table}>
    <tbody>
      <Row
        label="RSI signál"
        value={
          tech.rsi?.D > 70
            ? "🔴 Overbought"
            : tech.rsi?.D < 30
            ? "🟢 Oversold"
            : "⚪ Neutral"
        }
      />

      <Row label="EMA20" value={fmtUSD(tech.ema_20)} />
      <Row label="SMA50" value={fmtUSD(tech.sma_50)} />
      <Row label="SMA200" value={fmtUSD(tech.sma_200)} />

      <Row label="Trend" value={tech.trend} />
      <Row label="Počet svíček" value={tech.candle_count} />
    </tbody>
  </table>

            {/* Support zóny */}
            {zones.demand?.length > 0 && (
              <div style={{ marginTop: 16 }}>
                <div style={{ fontSize: 11, color: "#4ADE80", letterSpacing: "0.08em", textTransform: "uppercase", padding: "8px 12px 4px", fontWeight: 600 }}>
                  ▼ Demand zóny (týdenní swing low → denní anchor svíčka)
                </div>
                <table style={S.table}>
                  <thead>
                    <tr>
                      <th style={S.th}>Zóna (low – high)</th>
                      <th style={S.th}>Střed</th>
                      <th style={S.th}>Anchor svíčka</th>
                      <th style={S.th}>Týden swingu</th>
                    </tr>
                  </thead>
                  <tbody>
                    {zones.demand.map((z, i) => (
                      <tr key={i}>
                        <td style={{ ...S.td, ...S.pos, fontWeight: 600 }}>
                          {z.zone_low?.toFixed(2)} – {z.zone_high?.toFixed(2)} USD
                        </td>
                        <td style={S.td}>{z.zone_mid?.toFixed(2)} USD</td>
                        <td style={{ ...S.td, color: "#94A3B8" }}>{z.anchor_date ?? "—"}</td>
                        <td style={{ ...S.td, fontSize: 12, color: "#64748B" }}>{z.week_date ?? "—"}</td>
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
                  ▲ Supply zóny (týdenní swing high → denní anchor svíčka)
                </div>
                <table style={S.table}>
                  <thead>
                    <tr>
                      <th style={S.th}>Zóna (low – high)</th>
                      <th style={S.th}>Střed</th>
                      <th style={S.th}>Anchor svíčka</th>
                      <th style={S.th}>Týden swingu</th>
                    </tr>
                  </thead>
                  <tbody>
                    {zones.supply.map((z, i) => (
                      <tr key={i}>
                        <td style={{ ...S.td, ...S.neg, fontWeight: 600 }}>
                          {z.zone_low?.toFixed(2)} – {z.zone_high?.toFixed(2)} USD
                        </td>
                        <td style={S.td}>{z.zone_mid?.toFixed(2)} USD</td>
                        <td style={{ ...S.td, color: "#94A3B8" }}>{z.anchor_date ?? "—"}</td>
                        <td style={{ ...S.td, fontSize: 12, color: "#64748B" }}>{z.week_date ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Section>

      </div>
    </div>
  );
}
