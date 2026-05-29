export function ScorePanel({ scoreData }) {
  if (!scoreData) return null;

  const { total, breakdown } = scoreData;

  return (
    <div style={styles.wrapper}>
      
      {/* ✅ HEADER */}
      <div style={styles.header}>
        <div style={{ ...styles.score, color: getColor(total) }}>
          {total}/100
        </div>
        <div style={{ color: getColor(total), fontSize: 14 }}>
          {getLabel(total)}
        </div>
      </div>

      {/* ✅ BREAKDOWN */}
      <div style={styles.list}>
        <Row label="Valuation" value={breakdown.valuation} />
        <Row label="Growth" value={breakdown.growth} />
        <Row label="Profitability" value={breakdown.profitability} />
        <Row label="Health" value={breakdown.health} />
      </div>

    </div>
  );
}

function Row({ label, value }) {
  return (
    <div style={styles.row}>
      <span>{label}</span>
      <span style={{ color: getColor(value * 4) }}>
        {value} / 25
      </span>
    </div>
  );
}

function getColor(score) {
  if (score > 80) return "#22c55e";  // green
  if (score > 60) return "#84cc16";
  if (score > 40) return "#facc15";
  if (score > 20) return "#fb923c";
  return "#ef4444"; // red
}

function getLabel(score) {
  if (score > 80) return "Strong Bullish";
  if (score > 60) return "Bullish";
  if (score > 40) return "Neutral";
  if (score > 20) return "Bearish";
  return "High Risk";
}

const styles = {
  wrapper: {
    padding: 16,
    border: "1px solid #1f2937",
    borderRadius: 8,
    background: "#111827",
  },
  header: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: 12,
  },
  score: {
    fontSize: 26,
    fontWeight: "bold",
  },
  list: {
    display: "flex",
    flexDirection: "column",
    gap: 6,
  },
  row: {
    display: "flex",
    justifyContent: "space-between",
    fontSize: 14,
    color: "#9ca3af",
  },
};