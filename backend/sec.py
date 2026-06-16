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

def normalize_series(items):
    out = []
    for i in items:
        end = i.get("end")
        val = safe_float(i.get("val"))
        if end and val is not None:
            out.append({"end": end, "val": val})
    return out


def group_by_fiscal_year(series):
    groups = {}
    for s in series:
        fy = s["end"][:4]
        groups.setdefault(fy, []).append(s)

    for fy in groups:
        groups[fy].sort(key=lambda x: x["end"])

    return groups


def build_q4_from_annual(qs, annual_val, annual_end):
    if not qs or annual_val is None:
        return None

    qsum = sum(x["val"] for x in qs[:3])
    q4 = annual_val - qsum

    if q4 <= 0:
        return None

    return {
        "end": annual_end,
        "val": q4
    }

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


def extract_time_series(section, concept, n=20):
    """
    Vrátí quarterly sérii pro daný GAAP concept, nejnovější záznamy první.

    Strategie:
      1. Preferuj záznamy s fp in (Q1, Q2, Q3, Q4) — čisté quarterlies.
      2. Pokud quarterlies chybí nebo je jich méně než 4, rekonstruuj Q4
         z ročního záznamu (10-K) mínus Q1–Q3 daného FY.
      3. Omez výstup na záznamy z posledních 4 let (16 kvartálů stačí pro
         veškerou analýzu) — zabraňuje zobrazení dat z roku 2007.
    """
    import datetime as _dt

    values = section.get(concept, {}).get("units", {})
    if not values:
        return []

    # preferuj USD
    items = None
    for unit, arr in values.items():
        if "USD" in unit.upper():
            items = arr
            break
    if not items:
        items = next(iter(values.values()), [])
    if not items:
        return []

    # cutoff: záznamy starší než 5 let ignorujeme
    cutoff_year = _dt.date.today().year - 5
    cutoff = f"{cutoff_year}-01-01"

    # ── 1) Quarterly záznamy (fp Q1–Q4) ──────────────────────────────
    quarterly_fps = {"Q1", "Q2", "Q3", "Q4"}
    quarterlies = [
        i for i in items
        if i.get("fp") in quarterly_fps
        and i.get("end", "") >= cutoff
        and i.get("val") is not None
    ]

    # ── 2) Annual záznamy (10-K) pro Q4 rekonstrukci ─────────────────
    annual = [
        i for i in items
        if (i.get("form") or "").upper() == "10-K"
        and i.get("end", "") >= cutoff
        and i.get("val") is not None
    ]

    # ── 3) Q4 rekonstrukce ────────────────────────────────────────────
    reconstructed = []
    if annual:
        # seskup quarterlies podle FY
        fy_q: dict = {}
        for q in quarterlies:
            fy = q.get("fy") or q["end"][:4]
            fy_q.setdefault(fy, []).append(q)

        for ann in annual:
            fy = str(ann.get("fy") or ann["end"][:4])
            qs = sorted(fy_q.get(fy, []), key=lambda x: x["end"])
            if len(qs) >= 3:
                q4 = build_q4_from_annual(
                    [{"val": safe_float(q["val"])} for q in qs[:3]],
                    safe_float(ann["val"]),
                    ann["end"],
                )
                if q4:
                    # ujisti se, že Q4 datum není duplicitní s existujícím Q
                    exists = any(q["end"] == q4["end"] for q in quarterlies)
                    if not exists:
                        reconstructed.append(q4)

    # ── 4) Merge + dedupe ─────────────────────────────────────────────
    all_items = []
    for i in quarterlies:
        v = safe_float(i.get("val"))
        if v is not None:
            all_items.append({"end": i["end"], "val": v})
    all_items.extend(reconstructed)

    # fallback: pokud stále nemáme nic (firma nereportuje fp), vezmi
    # záznamy s délkou periody ~90 dní (start→end)
    if not all_items:
        for i in items:
            if i.get("end", "") < cutoff or i.get("val") is None:
                continue
            start = i.get("start", "")
            end   = i.get("end",   "")
            if start and end:
                try:
                    delta = (_dt.date.fromisoformat(end) - _dt.date.fromisoformat(start)).days
                    if 60 <= delta <= 135:   # přibližně čtvrtletní perioda
                        v = safe_float(i.get("val"))
                        if v is not None:
                            all_items.append({"end": end, "val": v})
                except Exception:
                    pass
            # pokud ani start nemáme, přidej cokoliv z posledních 5 let
            elif not start:
                v = safe_float(i.get("val"))
                if v is not None:
                    all_items.append({"end": end, "val": v})

    # dedupe by end (newest wins)
    seen: set = set()
    cleaned = []
    for x in sorted(all_items, key=lambda x: x["end"], reverse=True):
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

    # Revenue — rozšířený seznam kandidátů pokrývá i PFE/pharma
    revenue = pick_first_existing(gaap, [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
        "SalesRevenueGoodsNet",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "RevenuesNetOfInterestExpense",
    ])
    revenue = sorted(revenue, key=lambda x: x["end"], reverse=True)

    net_income = pick_first_existing(gaap, [
        "NetIncomeLoss",
        "ProfitLoss",
        "NetIncomeLossAvailableToCommonStockholdersBasic",
    ])
    net_income = sorted(net_income, key=lambda x: x["end"], reverse=True)

    op_income = pick_first_existing(gaap, [
        "OperatingIncomeLoss",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
    ])
    op_income = sorted(op_income, key=lambda x: x["end"], reverse=True)

    depreciation = pick_first_existing(gaap, [
        "DepreciationAndAmortization",
        "DepreciationDepletionAndAmortization",
        "Depreciation",
        "DepreciationAmortizationAndAccretion",
    ])
    depreciation = sorted(depreciation, key=lambda x: x["end"], reverse=True)

    revenue_ttm    = compute_ttm(revenue)
    net_income_val = compute_ttm(net_income)
    net_income_ttm = net_income_val if net_income_val and abs(net_income_val) < 1e12 else None

    result = {
        # klíče které main.py merge engine čte přes get("revenue") atd.
        "revenue":    revenue_ttm,
        "net_income": net_income_ttm,
        "fcf":        extract_fcf(gaap),
        "net_debt":   extract_net_debt(gaap),
        "eps_quarterly": extract_eps_quarterly(gaap),
        "shares":     shares,
        "source":     "sec",
        "confidence": 0.85,
        "history": {
            "revenue":          revenue,
            "net_income":       net_income,
            "operating_income": op_income,
            "depreciation":     depreciation,
        }
    }

    return result
