export const fmt = (n) => {
  if (n == null || isNaN(n)) return "—";
  const abs = Math.abs(n);
  if (abs >= 1e12) return (n / 1e12).toFixed(2) + " T";
  if (abs >= 1e9) return (n / 1e9).toFixed(2) + " B";
  if (abs >= 1e6) return (n / 1e6).toFixed(2) + " M";
  return n.toLocaleString("cs-CZ");
};

export const p2 = (n) => (n != null && !isNaN(n) ? n.toFixed(2) : "—");

export const pct = (n) =>
  n != null && !isNaN(n) ? (n * 100).toFixed(1) + " %" : "—";