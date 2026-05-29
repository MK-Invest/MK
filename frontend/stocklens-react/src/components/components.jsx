// CompanyHeader.jsx
export function CompanyHeader({ ticker, data }) {
  const f = data?.fundamentals || {};
  const price = data?.price;

  const fmt = (val, unit = "B") =>
    val != null ? `$${(val / 1e9).toFixed(1)}${unit}` : "N/A";

  const fmtPct = (val) =>
    val != null ? `${(val * 100).toFixed(1)}%` : "N/A";

  return (
    <div style={{
      marginBottom: 20,
      padding: 16,
      background: "#111827",
      borderRadius: 12,
      border: "1px solid #1f2937"
    }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
        <div style={{ fontSize: 22, fontWeight: "bold" }}>{ticker}</div>
        {price != null && (
          <div style={{ fontSize: 18, color: "#10B981", fontWeight: 600 }}>
            ${price.toFixed(2)}
          </div>
        )}
        {price == null && (
          <div style={{ fontSize: 13, color: "#EF4444" }}>cena nedostupná</div>
        )}
      </div>
      <div style={{ color: "#9CA3AF", fontSize: 14, marginTop: 6, display: "flex", gap: 16, flexWrap: "wrap" }}>
        <span>Revenue: {fmt(f.revenue)}</span>
        <span>Net Income: {fmt(f.net_income)}</span>
        <span>FCF: {fmt(f.fcf)}</span>
        <span>EBITDA margin: {fmtPct(f.ebitda_margin)}</span>
      </div>
    </div>
  );
}


// MetricsGrid.jsx
export function MetricsGrid({ data }) {
  if (!data) return null;

  // Všechna data jsou v data.fundamentals — ne přímo v data
  const f = data.fundamentals || {};
  const price = data.price;

  const fmt = (val, decimals = 1) =>
    val != null ? `$${(val / 1e9).toFixed(decimals)}B` : null;

  const fmtPct = (val) =>
    val != null ? `${(val * 100).toFixed(1)}%` : null;

  const fmtX = (val) =>
    val != null ? `${val.toFixed(1)}x` : null;

  const fmtPrice = (val) =>
    val != null ? `$${val.toFixed(2)}` : null;

  // Market cap a tržní metriky vyžadují cenu — počítáme lokálně
  const mc = price != null && f.shares ? price * f.shares : null;
  const ev = mc != null ? mc + (f.net_debt ?? (f.debt ?? 0) - (f.cash ?? 0)) : null;

  const pe  = mc && f.net_income  ? mc / f.net_income       : null;
  const ps  = mc && f.revenue     ? mc / f.revenue           : null;
  const pb  = mc && f.equity      ? mc / f.equity            : null;
  const eps = f.net_income && f.shares ? f.net_income / f.shares : null;
  const divYield = f.dps && price  ? f.dps / price           : null;

  const Card = ({ label, value, sub }) => (
    <div style={{
      background: "#111827",
      border: "1px solid #1f2937",
      borderRadius: 12,
      padding: 14,
    }}>
      <div style={{ fontSize: 12, color: "#6B7280", marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 18, fontWeight: 600, color: value ? "white" : "#374151" }}>
        {value ?? "N/A"}
      </div>
      {sub && (
        <div style={{ fontSize: 11, color: "#6B7280", marginTop: 2 }}>{sub}</div>
      )}
    </div>
  );

  // EPS quarterly — poslední 4
  const epsQ = f.eps_quarterly || [];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20, marginTop: 20 }}>

      {/* Tržní metriky */}
      <Section title="Tržní metriky">
        <Card label="Cena" value={fmtPrice(price)} />
        <Card label="Market Cap" value={mc ? `$${(mc / 1e12).toFixed(2)}T` : null} />
        <Card label="EV" value={fmt(ev)} />
        <Card label="P/E" value={fmtX(pe)} />
        <Card label="P/S" value={fmtX(ps)} />
        <Card label="P/B" value={fmtX(pb)} />
        <Card label="EV/EBITDA" value={ev && f.ebitda ? fmtX(ev / f.ebitda) : null} />
        <Card label="EV/FCF" value={ev && f.fcf ? fmtX(ev / f.fcf) : null} />
      </Section>

      {/* Výnosové metriky */}
      <Section title="Výnosové metriky">
        <Card label="Revenue (TTM)" value={fmt(f.revenue)} />
        <Card label="Net Income (TTM)" value={fmt(f.net_income)} />
        <Card label="EBITDA (TTM)" value={fmt(f.ebitda)} />
        <Card label="FCF (TTM)" value={fmt(f.fcf)} />
        <Card label="EBITDA Margin" value={fmtPct(f.ebitda_margin)} />
        <Card label="FCF Yield" value={mc && f.fcf ? fmtPct(f.fcf / mc) : null} />
        <Card label="Dividendový výnos" value={fmtPct(divYield)} sub={f.dps ? `$${f.dps.toFixed(2)} / akcii` : null} />
      </Section>

      {/* EPS */}
      <Section title="EPS">
        <Card label="EPS (TTM)" value={eps ? `$${eps.toFixed(2)}` : null} />
        {epsQ.map((q, i) => (
          <Card
            key={i}
            label={`EPS ${q.end}`}
            value={q.eps != null ? `$${q.eps.toFixed(2)}` : null}
          />
        ))}
      </Section>

      {/* Rentabilita */}
      <Section title="Rentabilita">
        <Card label="ROE" value={fmtPct(f.roe)} />
        <Card label="ROA" value={fmtPct(f.roa)} />
        <Card label="ROIC" value={fmtPct(f.roic)} />
        <Card label="Tax Rate" value={fmtPct(f.tax_rate)} />
        <Card label="NOPAT" value={fmt(f.nopat)} />
      </Section>

      {/* Rozvaha */}
      <Section title="Rozvaha">
        <Card label="Cash" value={fmt(f.cash)} />
        <Card label="Debt" value={fmt(f.debt)} />
        <Card label="Net Debt" value={fmt(f.net_debt)} />
        <Card label="Equity" value={fmt(f.equity)} />
        <Card label="Current Ratio" value={f.current_ratio?.toFixed(2) ?? null} />
        <Card label="D/E" value={f.equity && f.debt ? fmtX(f.debt / Math.abs(f.equity)) : null} />
        <Card label="Op. Working Capital" value={fmt(f.operating_working_capital)} />
      </Section>

    </div>
  );
}

// Pomocná sekce s nadpisem
function Section({ title, children }) {
  return (
    <div>
      <div style={{
        fontSize: 13,
        fontWeight: 500,
        color: "#6B7280",
        textTransform: "uppercase",
        letterSpacing: "0.06em",
        marginBottom: 10,
      }}>
        {title}
      </div>
      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(4, 1fr)",
        gap: 12,
      }}>
        {children}
      </div>
    </div>
  );
}
