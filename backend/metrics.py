"""
metrics.py — výpočet tržních a fundamentálních metrik
======================================================
Vstup: dict z get_stock_data() (merge SEC + TwelveData + FMP)
Výstup:
  quarters  — metriky za každý dostupný kvartál
  ttm       — trailing twelve months (kompletní sada)
  trend     — signály pro screening
"""


def compute_metrics(data: dict) -> dict:
    history = data.get("history") or {}

    price  = data.get("price")
    shares = data.get("shares")
    equity = data.get("equity")

    debt = data.get("debt") or 0
    cash = data.get("cash") or 0

    fcf           = data.get("fcf")
    roic          = data.get("roic")
    nopat         = data.get("nopat")
    net_debt      = data.get("net_debt")
    tax_rate      = data.get("tax_rate")
    roe           = data.get("roe")
    roa           = data.get("roa")
    current_ratio = data.get("current_ratio")
    dps           = data.get("dps")
    total_assets  = data.get("total_assets")
    eps_quarterly = data.get("eps_quarterly") or []
    volume        = data.get("volume")

    revenue_series    = history.get("revenue") or []
    net_income_series = history.get("net_income") or []
    op_series         = history.get("operating_income") or []
    dep_series        = history.get("depreciation") or []

    if not revenue_series:
        return {"quarters": [], "ttm": {}, "trend": {}}

    ebitda_series = compute_quarterly_ebitda(op_series, dep_series)

    mc = None
    ev = None
    if price is not None and shares not in (None, 0):
        mc = price * shares
        ev = mc + (net_debt if net_debt is not None else debt - cash)

    def align_by_end(series):
        return {x["end"]: x.get("val") for x in series if x and x.get("end")}

    revenue_map = align_by_end(revenue_series)
    ni_map      = align_by_end(net_income_series)
    ebitda_map  = {r["end"]: v for r, v in zip(revenue_series, ebitda_series) if r and v is not None}

    quarters = []

    for end in revenue_map.keys():
        rev = revenue_map.get(end)
        ni  = ni_map.get(end)
        eb  = ebitda_map.get(end)

        q = {
            "end": end,
            "revenue": rev,
            "net_income": ni,
            "ebitda": eb,
        }

        if mc is not None:
            q["market_cap"] = mc
            q["ev"] = ev

            if eb not in (None, 0):
                q["ev_ebitda"] = ev / eb

            if ni is not None and shares not in (None, 0):
                q["eps"] = ni / shares

            if ni not in (None, 0) and shares not in (None, 0):
                q["pe"] = mc / ni

            if rev not in (None, 0):
                q["ps"] = mc / rev

            if equity not in (None, 0):
                q["pb"] = mc / equity

        quarters.append(q)

    ttm = {}

    ttm_revenue    = data.get("revenue")
    ttm_net_income = data.get("net_income")
    ttm_ebitda     = data.get("ebitda")

    if mc is not None:
        ttm["market_cap"] = mc
        ttm["ev"] = ev

        ttm_ebitda_calc = compute_ttm_ebitda(ebitda_series)
        if ttm_ebitda_calc is not None:
            ttm["ebitda"] = ttm_ebitda_calc
        elif ttm_ebitda is not None:
            ttm["ebitda"] = ttm_ebitda

        ebitda_for_ratio = ttm.get("ebitda")
        if ebitda_for_ratio not in (None, 0):
            ttm["ev_ebitda"] = ev / ebitda_for_ratio

        if ttm_net_income not in (None, 0):
            ttm["pe"] = mc / ttm_net_income

        if ttm_revenue not in (None, 0):
            ttm["ps"] = mc / ttm_revenue

        if equity not in (None, 0):
            ttm["pb"] = mc / equity

        if ttm_net_income is not None and shares not in (None, 0):
            ttm["eps_ttm"] = ttm_net_income / shares

        if eps_quarterly:
            ttm["eps_quarterly"] = eps_quarterly

        if len(eps_quarterly) >= 2:
            eps_new = eps_quarterly[0].get("eps")
            eps_old = eps_quarterly[-1].get("eps")
            if eps_new is not None and eps_old not in (None, 0):
                ttm["eps_growth"] = (eps_new - eps_old) / abs(eps_old)

        if dps is not None and dps > 0 and price not in (None, 0):
            ttm["dividend_yield"] = dps / price
            ttm["dps"] = dps

    if fcf is not None:
        ttm["fcf"] = fcf
        if mc not in (None, 0):
            ttm["fcf_yield"] = fcf / mc
        if ev not in (None, 0) and fcf != 0:
            ttm["ev_fcf"] = ev / fcf

    if roic is not None: ttm["roic"] = roic
    if nopat is not None: ttm["nopat"] = nopat
    if tax_rate is not None: ttm["tax_rate"] = tax_rate
    if net_debt is not None: ttm["net_debt"] = net_debt
    if roe is not None: ttm["roe"] = roe
    if roa is not None: ttm["roa"] = roa

    if current_ratio is not None:
        ttm["current_ratio"] = current_ratio

    total_debt = debt
    if total_debt and equity not in (None, 0):
        ttm["de_ratio"] = total_debt / abs(equity)

    if volume is not None:
        ttm["volume"] = volume

    trend = {}

    if len(quarters) >= 2:
        r0 = quarters[0].get("revenue")
        r1 = quarters[1].get("revenue")
        if r0 is not None and r1 not in (None, 0):
            trend["revenue_up"] = r0 > r1
            trend["revenue_growth"] = (r0 - r1) / abs(r1)

    if len(eps_quarterly) >= 2:
        e0 = eps_quarterly[0].get("eps")
        e1 = eps_quarterly[1].get("eps")
        if e0 is not None and e1 is not None:
            trend["eps_up"] = e0 > e1

    if "eps_growth" in ttm:
        trend["eps_growing"] = ttm["eps_growth"] > 0
        trend["eps_growth_strong"] = ttm["eps_growth"] > 0.10

    if "fcf" in ttm:
        trend["fcf_positive"] = ttm["fcf"] > 0
    if "fcf_yield" in ttm:
        trend["fcf_strong"] = ttm["fcf_yield"] > 0.05

    if "roic" in ttm:
        trend["roic_good"] = ttm["roic"] > 0.10
        trend["roic_elite"] = ttm["roic"] > 0.20

    if "roe" in ttm:
        trend["roe_good"] = ttm["roe"] > 0.15
        trend["roe_elite"] = ttm["roe"] > 0.30

    if "current_ratio" in ttm:
        trend["liquid"] = ttm["current_ratio"] > 1.0
        trend["very_liquid"] = ttm["current_ratio"] > 2.0

    if "de_ratio" in ttm:
        trend["low_debt"] = ttm["de_ratio"] < 0.5
        trend["high_debt"] = ttm["de_ratio"] > 2.0

    if "dividend_yield" in ttm:
        trend["pays_dividend"] = ttm["dividend_yield"] > 0
        trend["high_yield_dividend"] = ttm["dividend_yield"] > 0.03

    return {
        "quarters": quarters,
        "ttm": ttm,
        "trend": trend,
    }

# =========================================================
# HELPERS
# =========================================================

def compute_quarterly_ebitda(op_series, dep_series):
    result = []
    length = min(len(op_series), len(dep_series))

    for i in range(length):
        op = op_series[i].get("val") if op_series[i] else None
        dep = dep_series[i].get("val") if dep_series[i] else None

        if op is None:
            result.append(None)
            continue

        dep = dep or 0
        result.append(op + dep)

    return result


def compute_ttm_ebitda(ebitda_series):
    if not ebitda_series or len(ebitda_series) < 4:
        return None
    vals = ebitda_series[:4]
    if any(v is None for v in vals):
        return None
    return sum(vals)
