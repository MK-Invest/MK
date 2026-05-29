export function computeScore(data) {
  const ttm = data?.metrics?.ttm ?? {};
  const trend = data?.metrics?.trend ?? {};

  let valuation = 0;
  let growth = 0;
  let profitability = 0;
  let health = 0;

  // ✅ VALUATION
  if (ttm.pe != null && ttm.pe < 20) valuation += 5;
  if (ttm.ev_ebitda != null && ttm.ev_ebitda < 12) valuation += 5;
  if ((ttm.fcf_yield ?? 0) > 0.05) valuation += 5;
  if (ttm.ev_fcf != null && ttm.ev_fcf < 20) valuation += 5;
  if (ttm.ps != null && ttm.ps < 4) valuation += 5;

  // ✅ GROWTH
  const eps = ttm.eps_growth ?? 0;

  if (eps > 0.10) {
    growth += 20;
  } else if (eps > 0) {
    growth += 10;
  }

  if (trend.revenue_up) growth += 5;

  // ✅ PROFITABILITY
  const roic = ttm.roic ?? 0;

  if (roic > 0.20) {
    profitability += 20;
  } else if (roic > 0.10) {
    profitability += 10;
  }

  if ((ttm.roe ?? 0) > 0.15) profitability += 5;

  // ✅ HEALTH
  const cr = ttm.current_ratio ?? 0;

  if (cr > 2) {
    health += 10;
  } else if (cr > 1.5) {
    health += 5;
  }

  if (ttm.de_ratio != null && ttm.de_ratio < 1) health += 5;
  if (trend.low_debt) health += 5;
  if (trend.fcf_positive) health += 5;

  // ✅ TOTAL
  const total = valuation + growth + profitability + health;

  return {
    total: Math.min(total, 100),
    breakdown: {
      valuation,
      growth,
      profitability,
      health,
    },
  };
}
