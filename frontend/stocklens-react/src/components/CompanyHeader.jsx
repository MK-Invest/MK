import { computeScore } from "../utils/scoring";
import { ScorePanel } from "./ScorePanel";

export function CompanyHeader({ ticker, data }) {
  const f = data?.fundamentals ?? {};
  const price = data?.price;

  const fmt = (val) =>
    val != null ? `$${(val / 1e9).toFixed(1)}B` : "N/A";

  const fmtPct = (val) =>
    val != null ? `${(val * 100).toFixed(1)}%` : "N/A";
  
  const scoreData = computeScore(data);

  return (
    <div>
      <h1>{ticker}</h1>

      <div>
        {price != null ? `$${price.toFixed(2)}` : "cena nedostupná"}
      </div>

      <div>
        Revenue: {fmt(f.revenue)}<br />
        Net Income: {fmt(f.net_income)}<br />
        FCF: {fmt(f.fcf)}<br />
        ROIC: {fmtPct(f.roic)}
      </div>
    </div>
  );
}
