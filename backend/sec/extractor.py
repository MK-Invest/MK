"""
backend/sec/extractor.py — hlavní orchestrace: skládá dohromady time series,
metrics a normalize moduly do finálního fundamentals dict pro daný ticker.
"""

from .utils import safe_float
from .timeseries import (
    extract_time_series,
    pick_first_existing,
    extract_latest_annual_series,
)
from .metrics import compute_ttm, compute_cagr_5y, compute_cagr_2y, compute_fcf_median


def select_best(items):
    """Vybere nejnovější roční (FY) záznam, nebo nejnovější vůbec."""
    if not items:
        return None
    annual = [i for i in items if i.get("fp") == "FY"]
    return max(annual or items, key=lambda x: x.get("end", ""))


def extract_latest_value(section, concept):
    """Vrátí nejnovější hodnotu pro daný koncept (libovolná jednotka)."""
    values = section.get(concept, {}).get("units", {})
    for _, items in values.items():
        if not items:
            continue
        best = select_best(items)
        if best:
            return safe_float(best.get("val"))
    return None


def pick_latest_scalar(section, candidates):
    """Vrátí nejnovější skalární hodnotu z prvního kandidáta, který má data (USD)."""
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


def extract_fcf(gaap):
    """FCF = TTM operating cash flow - TTM capex (absolutní hodnota)."""
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


def extract_cfo(gaap):
    """TTM cash from operations (bez odečtu CapEx) — pro DCF normalizaci u mega-cap tech."""
    cfo = pick_first_existing(gaap, [
        "NetCashProvidedByOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivities",
    ])
    return compute_ttm(cfo)


def extract_net_debt(gaap):
    """Net debt = (long-term + current debt) - cash."""
    lt   = pick_latest_scalar(gaap, ["LongTermDebt"]) or 0
    st   = pick_latest_scalar(gaap, ["DebtCurrent"]) or 0
    cash = pick_latest_scalar(gaap, ["CashAndCashEquivalentsAtCarryingValue"]) or 0
    return (lt + st) - cash


def extract_eps_quarterly(gaap, shares):
    """Posledních 4 kvartální EPS = net income / shares."""
    ni = pick_first_existing(gaap, ["NetIncomeLoss"])
    if not ni or not shares:
        return []
    return [{"end": q["end"], "eps": q["val"] / shares} for q in ni[:4] if q.get("val")]


def extract_fcf_quarterly_series(gaap, n=12):
    """
    Vrátí kvartální FCF sérii (CFO - CapEx per kvartál), DESC pořadí.
    Na rozdíl od extract_fcf_annual_history (roční, pro medián) tahle
    funkce dává kvartální body pro CAGR výpočet na kratším okně (2Y).

    Páruje CFO a CapEx podle 'end' data — pokud pro daný kvartál chybí
    jeden z páru, kvartál se přeskočí (raději méně bodů než špatný pár).
    """
    cfo   = pick_first_existing(gaap, [
        "NetCashProvidedByOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivities",
    ], n=n)
    capex = pick_first_existing(gaap, [
        "CapitalExpenditures",
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PurchaseOfPropertyPlantAndEquipmentNet",
        "PaymentsToAcquireProductiveAssets",
    ], n=n)

    capex_by_end = {c["end"]: c["val"] for c in capex}

    result = []
    for c in cfo:
        capex_val = capex_by_end.get(c["end"])
        if capex_val is None:
            continue
        result.append({"end": c["end"], "val": c["val"] - abs(capex_val)})

    return result


def extract_eps_series(net_income, shares):
    """
    Odvodí kvartální EPS sérii z existující net_income historie (DESC).
    Nevyžaduje samostatnou GAAP extrakci — EPS = net_income / shares,
    počítané ze stejných kvartálních bodů, co už máme.
    """
    if not net_income or not shares:
        return []
    return [
        {"end": q["end"], "val": q["val"] / shares}
        for q in net_income if q.get("val") is not None
    ]


def extract_fcf_annual_history(gaap, years=3):
    """
    Vrátí roční FCF historii (CFO - CapEx) za posledních N fiskálních let,
    odvozenou z 10-K/20-F (FY) záznamů — ne kvartálních.

    Používá se pro normalizaci DCF u firem s dočasně extrémním TTM FCF
    (PFE post-COVID propad, akviziční dluh, 3M spin-off restrukturalizace).
    """
    from .timeseries import extract_annual_only, dedupe_annual_by_year

    cfo_items = _section_units_any(gaap, [
        "NetCashProvidedByOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivities",
    ])
    capex_items = _section_units_any(gaap, [
        "CapitalExpenditures",
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PurchaseOfPropertyPlantAndEquipmentNet",
        "PaymentsToAcquireProductiveAssets",
    ])

    cfo_annual   = dedupe_annual_by_year(extract_annual_only(cfo_items))
    capex_annual = dedupe_annual_by_year(extract_annual_only(capex_items))

    capex_by_year = {c["end"][:4]: c["val"] for c in capex_annual}

    result = []
    for c in sorted(cfo_annual, key=lambda x: x["end"], reverse=True)[:years]:
        fy = c["end"][:4]
        capex_val = capex_by_year.get(fy)
        if capex_val is None:
            continue
        fcf_val = c["val"] - abs(capex_val)
        result.append({"end": c["end"], "fy": fy, "fcf": fcf_val})

    return result


def _section_units_any(section, candidates):
    """Vrátí raw items (se všemi poli) pro první kandidáta s USD daty."""
    for c in candidates:
        units = section.get(c, {}).get("units", {})
        for unit, items in units.items():
            if "USD" in unit.upper() and items:
                return items
    return []


def extract_fundamentals(data):
    """
    Hlavní orchestrace: vytáhne všechny fundamentální metriky pro danou
    firmu z raw SEC XBRL company facts dat.
    """
    facts = data.get("facts", {})
    gaap  = facts.get("us-gaap", {})

    shares = pick_latest_scalar_any_unit(gaap, [
        "CommonStockSharesOutstanding",
        "CommonStockSharesIssued",
        "EntityCommonStockSharesOutstanding",
    ])

    revenue_candidates = [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
        "SalesRevenueGoodsNet",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "RevenuesNetOfInterestExpense",
    ]
    revenue = pick_first_existing(gaap, revenue_candidates)
    revenue = sorted(revenue, key=lambda x: x["end"], reverse=True)
    revenue_annual = extract_latest_annual_series(gaap, revenue_candidates)

    net_income_candidates = [
        "NetIncomeLoss",
        "ProfitLoss",
        "NetIncomeLossAvailableToCommonStockholdersBasic",
    ]
    net_income = pick_first_existing(gaap, net_income_candidates)
    net_income = sorted(net_income, key=lambda x: x["end"], reverse=True)
    net_income_annual = extract_latest_annual_series(gaap, net_income_candidates)

    op_income = pick_first_existing(gaap, [
        "OperatingIncomeLoss",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
    ])
    op_income = sorted(op_income, key=lambda x: x["end"], reverse=True)

    revenue_cagr_5y    = compute_cagr_5y(revenue)
    net_income_cagr_5y = compute_cagr_5y(net_income)

    # EPS a FCF CAGR — kratší 2Y okno, doplňuje revenue_cagr_5y o kontext:
    # pokud revenue klesá ale EPS/FCF roste, jde o zlepšující se efektivitu/
    # marže (např. restrukturalizace), ne čistý fundamentální propad.
    # 2Y okno místo 5Y, aby nebylo zkreslené starou restrukturalizací/
    # spin-offem (stejný problém jaký řešil revenue_cagr_5y u MMM/3M).
    eps_series      = extract_eps_series(net_income, shares)
    fcf_q_series    = extract_fcf_quarterly_series(gaap)
    eps_cagr_2y     = compute_cagr_2y(eps_series)
    fcf_cagr_2y     = compute_cagr_2y(fcf_q_series)

    depreciation = pick_first_existing(gaap, [
        "DepreciationAndAmortization",
        "DepreciationDepletionAndAmortization",
        "Depreciation",
        "DepreciationAmortizationAndAccretion",
    ])
    depreciation = sorted(depreciation, key=lambda x: x["end"], reverse=True)

    # annual_series fallback: pokud chybí kompletní sada 4 čistých kvartálů
    # (mezera v SEC podáních, firma po spin-offu/restrukturalizaci),
    # použij nejnovější celoroční (10-K/20-F) hodnotu místo None.
    revenue_ttm    = compute_ttm(revenue, annual_series=revenue_annual)
    net_income_val = compute_ttm(net_income, annual_series=net_income_annual)
    net_income_ttm = net_income_val if net_income_val and abs(net_income_val) < 1e12 else None

    fcf_annual_history = extract_fcf_annual_history(gaap, years=3)
    fcf_3y_median = compute_fcf_median(fcf_annual_history)

    return {
        "revenue":            revenue_ttm,
        "net_income":         net_income_ttm,
        "fcf":                extract_fcf(gaap),
        "net_debt":           extract_net_debt(gaap),
        "eps_quarterly":      extract_eps_quarterly(gaap, shares),
        "shares":             shares,
        "cfo":                extract_cfo(gaap),
        "revenue_cagr_5y":    revenue_cagr_5y,
        "net_income_cagr_5y": net_income_cagr_5y,
        "eps_cagr_2y":        eps_cagr_2y,
        "fcf_cagr_2y":        fcf_cagr_2y,
        "fcf_3y_median":      fcf_3y_median,
        "fcf_annual_history": fcf_annual_history,
        "source":             "sec",
        "confidence":         0.85,
        "history": {
            "revenue":          revenue,
            "net_income":       net_income,
            "operating_income": op_income,
            "depreciation":     depreciation,
        }
    }
