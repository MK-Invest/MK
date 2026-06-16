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
    return {"end": annual_end, "val": q4}


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

    Jednoduchá strategie — bez řešení fiskálního roku:
      1. Vezmi všechny záznamy s end >= cutoff (5 let zpět).
      2. Čisté quarterly = záznamy kde end-start delta je 60–135 dní.
         Pro záznamy bez "start" pole akceptuj pouze fp=Q1 (vždy čistý)
         nebo záznamy z 10-Q kde neexistuje novější záznam se stejným end
         (deduplication).
      3. Rekonstruuj chybějící periody z ročního 10-K: Q_missing = FY - ostatní.
      4. Seřaď DESC a vrať posledních n záznamů.

    Tím je jedno jestli má firma kalendářní nebo posunutý fiskál —
    vždy dostaneš nejnovější dostupná data.
    """
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

    cutoff_year = datetime.date.today().year - 5
    cutoff = f"{cutoff_year}-01-01"

    recent = [i for i in items if i.get("end", "") >= cutoff and i.get("val") is not None]

    # ── Klasifikuj záznamy ───────────────────────────────────────────
    quarterly = []   # čisté quarterly záznamy
    annual    = []   # roční záznamy (10-K) pro rekonstrukci

    for i in recent:
        form  = (i.get("form") or "").upper()
        start = i.get("start", "")
        end   = i.get("end",   "")
        fp    = i.get("fp",    "")

        if "10-K" in form:
            annual.append(i)
            continue

        if start and end:
            try:
                delta = (datetime.date.fromisoformat(end) - datetime.date.fromisoformat(start)).days
                if 60 <= delta <= 135:
                    quarterly.append(i)
                # YTD kumulativy (delta > 135) ignoruj
            except Exception:
                pass
        else:
            # Bez "start" pole: akceptuj pouze fp=Q1 (vždy čistý ~90 dní od FY start)
            # Q2/Q3 bez start jsou potenciálně YTD → odmítni
            # Q4 rekonstruujeme z 10-K
            if fp == "Q1":
                quarterly.append(i)

    # ── Q4 rekonstrukce: Q4 = 10-K value − Q1 − Q2 − Q3 ────────────
    reconstructed = []
    # seskup quarterly podle (fy, end_year) — funguje pro oba typy fiskálu
    fy_q: dict = {}
    for q in quarterly:
        # klíč = rok end data (pro posunutý fiskál PFE: Q4 2024 má end 2024-12-31)
        key = str(q.get("fy") or q["end"][:4])
        fy_q.setdefault(key, []).append(q)

    for ann in annual:
        key = str(ann.get("fy") or ann["end"][:4])
        qs  = sorted(fy_q.get(key, []), key=lambda x: x["end"])
        if len(qs) >= 3:
            q4 = build_q4_from_annual(
                [{"val": safe_float(q["val"])} for q in qs[:3]],
                safe_float(ann["val"]),
                ann["end"],
            )
            if q4:
                # přidej jen pokud daný end ještě nemáme
                if not any(q["end"] == q4["end"] for q in quarterly):
                    reconstructed.append(q4)

    # ── Merge, dedupe, sort DESC ─────────────────────────────────────
    all_items = []
    for i in quarterly:
        v = safe_float(i.get("val"))
        if v is not None:
            all_items.append({"end": i["end"], "val": v})
    all_items.extend(reconstructed)

    # Fallback: pokud stále prázdné, vezmi roční záznamy
    if not all_items:
        for ann in annual:
            v = safe_float(ann.get("val"))
            if v is not None:
                all_items.append({"end": ann["end"], "val": v})

    seen: set = set()
    cleaned = []
    for x in sorted(all_items, key=lambda x: x["end"], reverse=True):
        if x["end"] not in seen:
            seen.add(x["end"])
            cleaned.append(x)

    return cleaned[:n]


def pick_first_existing(section, candidates, n=20):
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


def pick_latest_scalar_any_unit(section, candidates):
    """
    Jako pick_latest_scalar, ale prohledá i non-USD jednotky (shares, pure numbers).
    Použij pro CommonStockSharesOutstanding apod.
    """
    for concept in candidates:
        units = section.get(concept, {}).get("units", {})
        for unit_items in units.values():
            if not unit_items:
                continue
            best = select_best(unit_items)
            if best:
                v = safe_float(best.get("val"))
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
    cfo   = pick_first_existing(gaap, ["NetCashProvidedByOperatingActivities"])
    capex = pick_first_existing(gaap, [
        "CapitalExpenditures",
        "PaymentsToAcquirePropertyPlantAndEquipment",
    ])

    cfo_ttm   = compute_ttm(cfo)
    capex_ttm = compute_ttm(capex)

    if cfo_ttm is None or capex_ttm is None:
        return None

    return cfo_ttm - abs(capex_ttm)  # capex bývá záporný v CF, abs() pro jistotu


def extract_net_debt(gaap):
    lt   = pick_latest_scalar(gaap, ["LongTermDebt"]) or 0
    st   = pick_latest_scalar(gaap, ["DebtCurrent"]) or 0
    cash = pick_latest_scalar(gaap, ["CashAndCashEquivalentsAtCarryingValue"]) or 0
    return (lt + st) - cash


def extract_eps_quarterly(gaap, shares):
    ni = pick_first_existing(gaap, ["NetIncomeLoss"])
    if not ni or not shares:
        return []
    return [{"end": q["end"], "eps": q["val"] / shares} for q in ni[:4] if q.get("val")]


def extract_fundamentals(data):
    facts = data.get("facts", {})
    gaap  = facts.get("us-gaap", {})

    # Shares — prohledej i non-USD jednotky (PFE reportuje shares bez USD)
    shares = pick_latest_scalar_any_unit(gaap, [
        "CommonStockSharesOutstanding",
        "CommonStockSharesIssued",
        "EntityCommonStockSharesOutstanding",
    ])

    # Revenue — pořadí kandidátů: nejnovější GAAP standard první
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
        "revenue":       revenue_ttm,
        "net_income":    net_income_ttm,
        "fcf":           extract_fcf(gaap),
        "net_debt":      extract_net_debt(gaap),
        "eps_quarterly": extract_eps_quarterly(gaap, shares),
        "shares":        shares,
        "source":        "sec",
        "confidence":    0.85,
        "history": {
            "revenue":          revenue,
            "net_income":       net_income,
            "operating_income": op_income,
            "depreciation":     depreciation,
        }
    }

    return result
