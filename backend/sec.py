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


def _is_quarterly_period(i):
    """
    True pokud je záznam čistě čtvrtletní perioda (~60–135 dní).
    Filtruje YTD kumulativní záznamy (H1, 9M apod.).

    SEC data mají dva typy 10-Q záznamů:
      A) s polem "start" → přímý výpočet delta (spolehlivé)
      B) bez "start" → musíme použít fp pole, ALE fp="Q3" může být
         YTD (9 měsíců) nebo skutečný Q3. Rozlišení:
         - form="10-Q" + fp="Q1" → vždy čistý kvartál (~90 dní od FY start)
         - form="10-Q" + fp="Q2" → může být 6M YTD nebo čistý Q2
         - form="10-Q" + fp="Q3" → může být 9M YTD nebo čistý Q3
         Bezpečné pravidlo: přijmeme POUZE fp="Q1" bez start pole,
         Q2/Q3 bez start pole odmítneme (pravděpodobně YTD).
         Q4 se rekonstruuje z ročního záznamu.
    """
    start = i.get("start", "")
    end   = i.get("end",   "")
    fp    = i.get("fp", "")

    # Primární: start→end delta
    if start and end:
        try:
            delta = (datetime.date.fromisoformat(end) - datetime.date.fromisoformat(start)).days
            return 60 <= delta <= 135
        except Exception:
            pass

    # Sekundární: fp pole bez start
    if not start:
        # Q1 bez start = bezpečné (vždy ~90 dní od FY start)
        if fp == "Q1":
            return True
        # Q2/Q3 bez start = pravděpodobně YTD → odmítni
        if fp in {"Q2", "Q3"}:
            return False
        # Q4 bez start = nepoužívej přímo, rekonstruuj z 10-K
        if fp == "Q4":
            return False

    return False


def extract_time_series(section, concept, n=20):
    """
    Vrátí quarterly sérii pro daný GAAP concept, nejnovější záznamy první.

    Strategie:
      1. Filtruj jen čisté quarterly záznamy (perioda ~90 dní) — odstraní
         YTD/kumulativní záznamy z 10-Q i roční záznamy z 10-K.
      2. Rekonstruuj Q4 = FY − Q1−Q2−Q3 z ročního záznamu (10-K).
      3. Omez na záznamy z posledních 5 let.
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

    # ── 1) Čisté quarterly záznamy ───────────────────────────────────
    # Záznamy bez "start" pole a fp=Q2/Q3 jsou potenciálně YTD kumulativní.
    # Pro firmy kde SEC data mají "start" u všech quarterly → _is_quarterly_period() postačí.
    # Pro firmy kde "start" chybí (PFE apod.) → zkusíme YTD dedukci z hodnot (viz níže).
    quarterlies_raw = [
        i for i in items
        if i.get("fp") in {"Q1", "Q2", "Q3", "Q4"}
        and i.get("end", "") >= cutoff
        and i.get("val") is not None
    ]
    # Preferuj záznamy s "start" polem (delta-check spolehlivý)
    has_start = any(i.get("start") for i in quarterlies_raw)
    if has_start:
        quarterlies = [i for i in quarterlies_raw if _is_quarterly_period(i)]
    else:
        # Bez "start": Q1 je vždy čistý, Q2/Q3 mohou být YTD.
        # Pokus o detekci YTD: pokud val[Q2] > val[Q1]*1.5 v témže FY → pravděpodobně YTD.
        # V takovém případě odmítneme Q2/Q3 a spoléháme na Q4 rekonstrukci.
        q1_vals_by_fy = {}
        for i in quarterlies_raw:
            if i.get("fp") == "Q1":
                fy = str(i.get("fy") or i["end"][:4])
                q1_vals_by_fy[fy] = safe_float(i.get("val")) or 0

        quarterlies = []
        for i in quarterlies_raw:
            fp = i.get("fp")
            fy = str(i.get("fy") or i["end"][:4])
            val = safe_float(i.get("val")) or 0
            q1 = q1_vals_by_fy.get(fy, 0)

            if fp == "Q1":
                quarterlies.append(i)
            elif fp == "Q2":
                # YTD Q2 by byl ~2× Q1; čistý Q2 by byl podobný Q1
                if q1 > 0 and val > q1 * 1.7:
                    pass  # pravděpodobně YTD → přeskoč
                else:
                    quarterlies.append(i)
            elif fp == "Q3":
                # YTD Q3 by byl ~3× Q1; čistý Q3 by byl podobný Q1
                if q1 > 0 and val > q1 * 2.2:
                    pass  # pravděpodobně YTD → přeskoč
                else:
                    quarterlies.append(i)
            # Q4 přeskočíme, rekonstruujeme z 10-K

    # ── 2) Annual záznamy pro Q4 rekonstrukci ────────────────────────
    annual = [
        i for i in items
        if (i.get("form") or "").upper() == "10-K"
        and i.get("end", "") >= cutoff
        and i.get("val") is not None
    ]

    # ── 3) Q4 rekonstrukce: Q4 = FY − Q1 − Q2 − Q3 ──────────────────
    reconstructed = []
    if annual:
        fy_q = {}
        for q in quarterlies:
            fy = str(q.get("fy") or q["end"][:4])
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
                    exists = any(q["end"] == q4["end"] for q in quarterlies)
                    if not exists:
                        reconstructed.append(q4)

    # ── 4) Merge ──────────────────────────────────────────────────────
    all_items = []
    for i in quarterlies:
        v = safe_float(i.get("val"))
        if v is not None:
            all_items.append({"end": i["end"], "val": v})
    all_items.extend(reconstructed)

    # Fallback: pokud stále prázdné (žádné quarterly), vrať alespoň roční
    if not all_items and annual:
        for ann in annual:
            v = safe_float(ann.get("val"))
            if v is not None:
                all_items.append({"end": ann["end"], "val": v})

    # ── 5) Dedupe + sort DESC ─────────────────────────────────────────
    seen = set()
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
