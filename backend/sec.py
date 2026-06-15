import datetime
import math
import requests
from collections import defaultdict

HEADERS = {
    "User-Agent": "StockLens/1.0 (martin.kotek.317066@gmail.com)",
    "Accept-Encoding": "gzip, deflate",
    "Accept": "application/json"
}

SEC_CIK_URL = "https://www.sec.gov/files/company_tickers.json"


def safe_float(x):
    try:
        if x is None:
            return None
        if isinstance(x, str):
            x = x.replace(",", "")
        v = float(x)
        if math.isnan(v) or math.isinf(v):
            return None
        return v
    except Exception:
        return None


def select_best(items):
    if not items:
        return None
    annual = [i for i in items if i.get("fp") == "FY"]
    return max(annual or items, key=lambda x: x.get("end", ""))


def _parse_date(d):
    try:
        return datetime.date.fromisoformat(d)
    except Exception:
        return None


def get_cik_map():
    try:
        r = requests.get(SEC_CIK_URL, headers=HEADERS, timeout=30)
        r.raise_for_status()
        data = r.json()
        return {
            item["ticker"].upper(): {
                "cik": str(item["cik_str"]).zfill(10),
                "name": item.get("title", item["ticker"])
            }
            for item in data.values()
        }
    except Exception:
        return {}


def get_company_facts(cik: str):
    cik_padded = str(cik).zfill(10)
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik_padded}.json"
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        if r.status_code != 200:
            return None
        data = r.json()
        return data if "facts" in data else None
    except Exception:
        return None


def extract_latest_value(section, concept):
    values = section.get(concept, {}).get("units", {})
    for _, items in values.items():
        if not items:
            continue
        best = select_best(items)
        if best:
            return safe_float(best.get("val"))
    return None


def extract_time_series(section, concept, n=4):
    values = section.get(concept, {}).get("units", {})
    if not values:
        return []

    items = None
    for unit, arr in values.items():
        if "USD" in unit.upper():
            items = arr
            break
    if not items:
        items = next(iter(values.values()), [])

    if not items:
        return []

    quarterly = [i for i in items if (i.get("form") or "").upper() == "10-Q"]
    annual = [i for i in items if (i.get("form") or "").upper() == "10-K"]

    quarterly.sort(key=lambda x: x.get("end", ""))

    fy_groups = defaultdict(list)
    for q in quarterly:
        fy = (q.get("fy") or q.get("end", "")[:4])
        fy_groups[fy].append(q)

    derived = []

    for fy, qs in fy_groups.items():
        qs = sorted(qs, key=lambda x: x.get("end", ""))

        for q in qs:
            v = safe_float(q.get("val"))
            if v is not None:
                derived.append({"end": q["end"], "val": v})

        fy_annual = next((a for a in annual if a.get("fy") == fy), None)
        if fy_annual:
            fy_val = safe_float(fy_annual.get("val"))
            if fy_val is not None and len(qs) >= 3:
                q4 = fy_val - sum(safe_float(v.get("val")) or 0 for v in qs[:3])
                if 0 < q4 < fy_val:
                    derived.append({"end": fy_annual["end"], "val": q4})

    seen = set()
    cleaned = []
    for x in sorted(derived, key=lambda x: x["end"], reverse=True):
        if x["end"] not in seen:
            seen.add(x["end"])
            cleaned.append(x)

    return cleaned[:n]


def pick_first_existing(section, candidates, n=4):
    for c in candidates:
        s = extract_time_series(section, c, n)
        if s:
            return s
    return []


def pick_latest_scalar(section, candidates):
    for c in candidates:
        v = extract_latest_value(section, c)
        if v is not None:
            return v
    return None


def compute_ttm(series, annual_series=None):
    if not series:
        return None

    if len(series) >= 4:
        vals = [x["val"] for x in series[:4] if x.get("val") is not None]
        if len(vals) == 4:
            return sum(vals)

    if annual_series:
        return sorted(annual_series, key=lambda x: x["end"], reverse=True)[0]["val"]

    return series[0]["val"] if len(series) == 1 else None


def extract_fcf(gaap):
    cfo = pick_first_existing(gaap, ["NetCashProvidedByOperatingActivities"])
    capex = pick_first_existing(gaap, ["CapitalExpenditures"])

    cfo_ttm = compute_ttm(cfo)
    capex_ttm = compute_ttm(capex)

    if cfo_ttm is None or capex_ttm is None:
        return None

    if cfo_ttm is None or capex_ttm is None:
        return None

    return cfo_ttm - capex_ttm


def extract_net_debt(gaap):
    lt = pick_latest_scalar(gaap, ["LongTermDebt"]) or 0
    st = pick_latest_scalar(gaap, ["DebtCurrent"]) or 0
    cash = pick_latest_scalar(gaap, ["CashAndCashEquivalentsAtCarryingValue"]) or 0
    return (lt + st) - cash


def extract_eps_quarterly(gaap):
    ni = pick_first_existing(gaap, ["NetIncomeLoss"])
    shares = pick_latest_scalar(gaap, ["CommonStockSharesOutstanding"])

    if not ni or not shares:
        return []

    return [{"end": q["end"], "eps": q["val"] / shares} for q in ni[:4] if q.get("val")]


def extract_fundamentals(data):
    facts = data.get("facts", {})
    gaap = facts.get("us-gaap", {})
    shares = pick_latest_scalar(gaap, ["CommonStockSharesOutstanding"])
    revenue = pick_first_existing(gaap, [
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "SalesRevenueNet"
    ])

    net_income = pick_first_existing(gaap, [
        "NetIncomeLoss",
        "ProfitLoss"
    ])

    op_income = pick_first_existing(gaap, ["OperatingIncomeLoss"])
    depreciation = pick_first_existing(gaap, [
        "DepreciationAndAmortization",
        "Depreciation",
        "DepreciationDepletionAndAmortization"
    ])

    result = {
        "revenue": compute_ttm(revenue),
        "net_income": compute_ttm(net_income),
        "fcf": extract_fcf(gaap),
        "net_debt": extract_net_debt(gaap),
        "eps_quarterly": extract_eps_quarterly(gaap),
        "shares": shares,
        "history": {
            "revenue": revenue,
            "net_income": net_income,
            "operating_income": op_income,
            "depreciation": depreciation
        }
    }

    return result
