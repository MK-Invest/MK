def compute_metrics(data: dict) -> dict:
    history = data.get("history") or {}

    price = data.get("price")
    shares = data.get("shares")
    equity = data.get("equity")

    debt = data.get("debt") or 0
    cash = data.get("cash") or 0

    revenue_series = history.get("revenue") or []
    net_income_series = history.get("net_income") or []
    op_series = history.get("operating_income") or []
    dep_series = history.get("depreciation") or []

    # =========================
    # EARLY EXIT SAFETY
    # =========================
    if not revenue_series:
        return {"quarters": [], "ttm": {}, "trend": {}}

    # =========================
    # EBITDA
    # =========================
    ebitda_series = compute_quarterly_ebitda(op_series, dep_series)

    quarters = []

    # =========================
    # QUARTERLY METRICS
    # =========================
    for i in range(len(revenue_series)):
        rev_item = revenue_series[i] or {}
        rev = rev_item.get("val")

        ni = None
        if i < len(net_income_series) and net_income_series[i]:
            ni = net_income_series[i].get("val")

        ebitda = None
        if i < len(ebitda_series):
            ebitda = ebitda_series[i]

        q = {
            "end": rev_item.get("end"),
            "revenue": rev,
            "net_income": ni,
            "ebitda": ebitda
        }

        # =========================
        # MARKET METRICS
        # =========================
        if price is not None and shares not in (None, 0):
            mc = price * shares
            ev = mc + debt - cash

            q["market_cap"] = mc
            q["ev"] = ev

            # EV/EBITDA
            if ebitda not in (None, 0):
                q["ev_ebitda"] = ev / ebitda

            # EPS
            if ni is not None:
                q["eps"] = ni / shares

            # P/E
            if ni not in (None, 0):
                q["pe"] = mc / ni

            # P/S
            if rev not in (None, 0):
                q["ps"] = mc / rev

            # P/B
            if equity not in (None, 0):
                q["pb"] = mc / equity

        quarters.append(q)

    # =========================
    # TTM METRICS
    # =========================
    ttm = {}

    ttm_revenue = data.get("revenue")
    ttm_net_income = data.get("net_income")

    if price is not None and shares not in (None, 0):
        mc = price * shares
        ev = mc + debt - cash

        ttm["market_cap"] = mc
        ttm["ev"] = ev

        ttm_ebitda = compute_ttm_ebitda(ebitda_series)
        ttm["ebitda"] = ttm_ebitda

        if ttm_ebitda not in (None, 0):
            ttm["ev_ebitda"] = ev / ttm_ebitda

        if ttm_net_income not in (None, 0):
            ttm["pe"] = mc / ttm_net_income

        if ttm_revenue not in (None, 0):
            ttm["ps"] = mc / ttm_revenue

        if equity not in (None, 0):
            ttm["pb"] = mc / equity

        if ttm_net_income is not None:
            ttm["eps"] = ttm_net_income / shares

    # =========================
    # TREND (SAFE COMPARISON)
    # =========================
    trend = {}

    if len(quarters) >= 2:
        r0 = quarters[0].get("revenue")
        r1 = quarters[1].get("revenue")

        if r0 is not None and r1 is not None:
            trend["revenue_up"] = r0 > r1

        e0 = quarters[0].get("eps")
        e1 = quarters[1].get("eps")

        if e0 is not None and e1 is not None:
            trend["eps_up"] = e0 > e1

    return {
        "quarters": quarters,
        "ttm": ttm,
        "trend": trend
    }


# =========================
# EBITDA HELPERS (SAFE)
# =========================

def compute_quarterly_ebitda(op_series, dep_series):
    result = []

    length = min(len(op_series), len(dep_series))

    for i in range(length):
        op = None
        dep = None

        if op_series[i]:
            op = op_series[i].get("val")

        if dep_series[i]:
            dep = dep_series[i].get("val")

        if op is None or dep is None:
            result.append(None)
        else:
            result.append(op + dep)

    return result


def compute_ttm_ebitda(ebitda_series):
    if not ebitda_series or len(ebitda_series) < 4:
        return None

    vals = ebitda_series[:4]

    if any(v is None for v in vals):
        return None

    return sum(vals)
