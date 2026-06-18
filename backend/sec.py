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


def _dedupe_by_end(items):
    """Deduplikace podle end data, nejnovější verze vyhrává."""
    seen = set()
    result = []
    for x in sorted(items, key=lambda x: x["end"], reverse=True):
        if x["end"] not in seen:
            seen.add(x["end"])
            result.append(x)
    return result


def _filter_quarterly_by_delta(items, cutoff):
    """
    Filtruje záznamy kde start->end delta je 60–135 dní (čisté quarterly).
    Vrátí jen záznamy kde start pole existuje.
    """
    result = []
    for i in items:
        if i.get("end", "") < cutoff or i.get("val") is None:
            continue
        start = i.get("start", "")
        end   = i.get("end", "")
        if not start:
            continue
        try:
            delta = (datetime.date.fromisoformat(end) - datetime.date.fromisoformat(start)).days
            if 60 <= delta <= 135:
                result.append({"end": end, "val": safe_float(i["val"])})
        except Exception:
            pass
    return result


def _ytd_to_quarterly(items, cutoff):
    """
    Konverze YTD kumulativních záznamů na čisté quarterly hodnoty.
    Používá se pro firmy bez 'start' pole (např. PFE) kde SEC vrací
    YTD hodnoty pod fp=Q1/Q2/Q3.

    Logika:
      Q1 = YTD_Q1                (přímý, vždy čistý)
      Q2 = YTD_Q2 - YTD_Q1
      Q3 = YTD_Q3 - YTD_Q2
      Q4 = FY_annual - YTD_Q3   (z 10-K)

    Výsledek: list {"end": ..., "val": ...} čistých quarterly hodnot.
    """
    # Seskup podle roku end data (funguje pro posunutý i kalendářní fiskál)
    by_year = {}
    for i in items:
        if i.get("end", "") < cutoff or i.get("val") is None:
            continue
        year = i["end"][:4]
        fp   = i.get("fp", "")
        form = (i.get("form") or "").upper()
        v    = safe_float(i["val"])
        if v is None:
            continue
        if fp in ("Q1", "Q2", "Q3"):
            by_year.setdefault(year, {})[fp] = {"end": i["end"], "val": v}
        elif "10-K" in form or fp in ("FY", "A"):
            by_year.setdefault(year, {})["FY"] = {"end": i["end"], "val": v}

    result = []
    for year, periods in by_year.items():
        q1     = periods.get("Q1")
        q2_ytd = periods.get("Q2")
        q3_ytd = periods.get("Q3")
        fy_ann = periods.get("FY")

        # Q1 — přímá hodnota
        if q1:
            result.append({"end": q1["end"], "val": q1["val"]})

        # Q2 = YTD_Q2 - Q1
        if q1 and q2_ytd and q2_ytd["val"] > q1["val"]:
            result.append({"end": q2_ytd["end"], "val": q2_ytd["val"] - q1["val"]})

        # Q3 = YTD_Q3 - YTD_Q2
        if q2_ytd and q3_ytd and q3_ytd["val"] > q2_ytd["val"]:
            result.append({"end": q3_ytd["end"], "val": q3_ytd["val"] - q2_ytd["val"]})

        # Q4 = FY - YTD_Q3
        if q3_ytd and fy_ann and fy_ann["val"] > q3_ytd["val"]:
            result.append({"end": fy_ann["end"], "val": fy_ann["val"] - q3_ytd["val"]})
        # Q4 = FY - Q1 (pokud máme jen Q1 a FY)
        elif q1 and fy_ann and not q2_ytd and not q3_ytd:
            q4_val = fy_ann["val"] - q1["val"]
            if q4_val > 0:
                result.append({"end": fy_ann["end"], "val": q4_val})

    return result


def extract_time_series(section, concept, n=20):
    """
    Vrátí quarterly sérii pro daný GAAP concept, nejnovější záznamy první.

    Dvě strategie podle toho co SEC vrátí:
    A) Záznamy mají 'start' pole → delta filtr 60-135 dní (spolehlivé)
    B) Záznamy nemají 'start' pole → filtr podle rozestupu end dat
       (detekuje kumulativy protože ty mají end datumy blízko u sebe
       v rámci roku, zatímco čisté quarterly jsou ~90 dní od sebe)

    Navíc: Q4 rekonstrukce z 10-K.
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

    # ── Strategie A: záznamy se start polem ──────────────────────────
    has_start = any(i.get("start") for i in items if i.get("end", "") >= cutoff)

    if has_start:
        quarterly = _filter_quarterly_by_delta(items, cutoff)
    else:
        # ── Strategie B: YTD→quarterly konverze ──────────────────────
        quarterly = _ytd_to_quarterly(items, cutoff)

    # ── Roční záznamy pro Q4 rekonstrukci ────────────────────────────
    annual = [
        i for i in items
        if (i.get("form") or "").upper() == "10-K"
        and i.get("end", "") >= cutoff
        and i.get("val") is not None
    ]

    # ── Q4 rekonstrukce ──────────────────────────────────────────────
    reconstructed = []
    if annual:
        fy_q: dict = {}
        for q in quarterly:
            key = q["end"][:4]
            fy_q.setdefault(key, []).append(q)

        for ann in annual:
            key = ann["end"][:4]
            qs  = sorted(fy_q.get(key, []), key=lambda x: x["end"])
            if len(qs) >= 3:
                q4 = build_q4_from_annual(
                    qs[:3],
                    safe_float(ann["val"]),
                    ann["end"],
                )
                if q4 and not any(q["end"] == q4["end"] for q in quarterly):
                    reconstructed.append(q4)

    # ── Merge + dedupe + sort DESC ────────────────────────────────────
    all_items = quarterly + reconstructed

    # Fallback: pokud stále prázdné, vezmi roční záznamy
    if not all_items:
        for ann in annual:
            v = safe_float(ann.get("val"))
            if v is not None:
                all_items.append({"end": ann["end"], "val": v})

    return _dedupe_by_end(all_items)[:n]


def pick_first_existing(section, candidates, n=20):
    """
    Vrátí sérii od kandidáta s NEJNOVĚJŠÍMI daty.
    Pokud více kandidátů má záznamy, vyhraje ten s nejnovějším end datem.
    Tím se správně vybere 'Revenues' nad 'RevenueFromContractWithCustomer...'
    i když oba mají záznamy, ale druhý má novější data (např. PFE po 2022).
    """
    best_series = []
    best_end = ""

    for c in candidates:
        s = extract_time_series(section, c, n)
        if not s:
            continue
        newest = s[0]["end"]  # series je DESC, první = nejnovější
        if newest > best_end:
            best_end = newest
            best_series = s

    return best_series


def pick_latest_scalar(section, candidates):
    for c in candidates:
        v = extract_latest_value(section, c)
        if v is not None:
            return v
    return None


def pick_latest_scalar_any_unit(section, candidates):
    """
    Prohledá i non-USD jednotky (shares, pure numbers).
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
    cfo = pick_first_existing(gaap, [
        "NetCashProvidedByOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivities",
    ])
    capex = pick_first_existing(gaap, [
        "CapitalExpenditures",
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PurchaseOfPropertyPlantAndEquipmentNet",
        "PaymentsToAcquireProductiveAssets",
    ])

    cfo_ttm   = compute_ttm(cfo)
    capex_ttm = compute_ttm(capex)

    if cfo_ttm is None or capex_ttm is None:
        return None

    return cfo_ttm - abs(capex_ttm)

def extract_cfo(gaap) -> Optional[float]:
    cfo = pick_first_existing(gaap, [
        "NetCashProvidedByOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivities",
    ])
    return compute_ttm(cfo)

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

def compute_cagr_5y(series: list[dict]) -> float | None:
    """
    Spočítá 5Y CAGR z quarterly série (DESC pořadí, nejnovější první).
    Hledá hodnotu před ~5 lety (20 kvartálů zpět).
    Vrátí None pokud nemáme dostatek dat.
    """
    if not series or len(series) < 8:
        return None

    newest = series[0].get("val")
    if not newest or newest <= 0:
        return None

    # Vezmi hodnotu co nejblíže 20 kvartálům zpět (5 let)
    target_idx = min(19, len(series) - 1)
    oldest = series[target_idx].get("val")
    if not oldest or oldest <= 0:
        return None

    # Počet let podle skutečného datového rozpětí
    try:
        date_new = datetime.date.fromisoformat(series[0]["end"])
        date_old = datetime.date.fromisoformat(series[target_idx]["end"])
        years = (date_new - date_old).days / 365.25
        if years < 1:
            return None
    except Exception:
        years = target_idx / 4  # fallback: počet kvartálů / 4

    cagr = (newest / oldest) ** (1 / years) - 1

    # Sanitace — CAGR mimo -50% až +100% je podezřelý
    if not (-0.50 <= cagr <= 1.00):
        return None

    return cagr

def extract_fundamentals(data):
    facts = data.get("facts", {})
    gaap  = facts.get("us-gaap", {})

    shares = pick_latest_scalar_any_unit(gaap, [
        "CommonStockSharesOutstanding",
        "CommonStockSharesIssued",
        "EntityCommonStockSharesOutstanding",
    ])

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

    # Po řádku kde sestavuješ revenue, net_income série:
    revenue_cagr_5y    = compute_cagr_5y(revenue)
    net_income_cagr_5y = compute_cagr_5y(net_income)

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

    return {
        "revenue":       revenue_ttm,
        "net_income":    net_income_ttm,
        "fcf":           extract_fcf(gaap),
        "net_debt":      extract_net_debt(gaap),
        "eps_quarterly": extract_eps_quarterly(gaap, shares),
        "shares":        shares,
        "cfo": extract_cfo(gaap),
        "revenue_cagr_5y":    revenue_cagr_5y,      # ← nové
        "net_income_cagr_5y": net_income_cagr_5y,   # ← nové
        "source":        "sec",
        "confidence":    0.85,
        "history": {
            "revenue":          revenue,
            "net_income":       net_income,
            "operating_income": op_income,
            "depreciation":     depreciation,
        }
    }
