const RsiHeatmap = ({ rsi }) => {
  if (!rsi) return null;

  const getColor = (v) => {
    if (v == null) return "#444";
    if (v > 70) return "#ef4444"; // red
    if (v < 30) return "#22c55e"; // green
    return "#f59e0b"; // amber
  };

  const getLabel = (v) => {
    if (v == null) return "-";
    return v.toFixed(1);
  };

  const box = (label, value) => (
    <div
      style={{
        flex: 1,
        padding: "12px 10px",
        borderRadius: 10,
        background: getColor(value),
        color: "white",
        textAlign: "center",
        fontWeight: 600,
      }}
    >
      <div style={{ fontSize: 12, opacity: 0.9 }}>{label}</div>
      <div style={{ fontSize: 16 }}>{getLabel(value)}</div>
    </div>
  );

  return (
    <div style={{ display: "flex", gap: 8 }}>
      {box("RSI D", rsi.D)}
      {box("RSI W", rsi.W)}
      {box("RSI M", rsi.M)}
    </div>
  );
};

export default RsiHeatmap;