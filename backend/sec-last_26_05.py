import requests
import math
from typing import Any

HEADERS = {
    "User-Agent": "StockLens/1.0 (martin.kotek.317066@gmail.com)",
    "Accept-Encoding": "gzip, deflate",
    "Accept": "application/json"
}

SEC_CIK_URL = "https://www.sec.gov/files/company_tickers.json"


# =========================================================
# CIK MAP
# =========================================================

def get_cik_map():
    try:
        r = requests.get(SEC_CIK_URL, headers=HEADERS, timeout=30)
        r.raise_for_status()
        data = r.json()

        return {
            item["ticker"].upper(): str(item["cik_str"]).zfill(10)
            for item in data.values()
        }

    except Exception:
        return {}


# =========================================================
# SEC COMPANY FACTS
# =========================================================

def get_company_facts(cik: str):
    # BUG FIX: SEC URL vyžaduje CIK s nulami (CIK0000320193),
    # lstrip("0") je odstraňoval → 404. Zachováme zfill(10).
    cik_padded = str(cik).zfill(10)
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik_padded}.json"

    try:
        r = requests.get(url, headers=HEADERS, timeout=30)

        if r.status_code != 200:
            return None

        data = r.json()

        if not isinstance(data, dict) or "facts" not in data:
            return None

        return data

    except Exception:
        return None


# =========================================================
# UTIL
# =========================================================

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
    """Vybere nejnovější FY záznam, fallback na jakýkoliv nejnovější."""
    if not items:
        return None

    annual = [i for i in items if i.get("fp") == "FY"]
    if annual:
        return max(annual, key=lambda x: x.get("end", ""))

    return max(items, key=lambda x: x.get("end", ""))


# =========================================================
# EXTRACTION HELPERS
# =========================================================

def extract_latest_value(section, concept):
    values = section.get(concept, {}).get("units", {})
    if not values:
        return None

    for unit, items in values.items():
        if not items:
            continue

        best = select_best(items)
        if not best:
            continue

        return safe_float(best.get("val"))

    return None


def extract_time_series(section, concept, n=4):
    """
    Vrátí časovou řadu posledních n čtvrtletních hodnot.

    Klíčové pravidlo SEC dat:
    - form="10-Q", fp="Q1/Q2/Q3" → skutečné čtvrtletní výsledky ✓
    - form="10-K", fp="FY"       → roční výsledky (použij pokud chybí quarterly)
    - form="10-K", fp="Q1/Q2/Q3" → klouzavé YTD součty z ročního výkazu ✗ ZAHOĎ
    - form="10-Q", fp="FY"       → neobvyklé, ignoruj

    Revenue z Apple reportuje FY jako jeden roční záznam (10-K/FY),
    quarterly jsou v 10-Q/Q1-Q3. Q4 se dopočítá jako FY - Q1 - Q2 - Q3.
    """
    values = section.get(concept, {}).get("units", {})
    if not values:
        return []

    # Preferuj USD jednotky
    items = None
    for unit, arr in values.items():
        if "USD" in unit.upper():
            items = arr
            break
    if not items:
        items = next(iter(values.values()), [])
    if not items:
        return []

    # Rozdělení podle form + fp — klíčový fix
    true_quarterly = []   # 10-Q s fp Q1/Q2/Q3
    true_annual    = []   # 10-K s fp FY

    for item in items:
        form = (item.get("form") or "").upper()
        fp   = (item.get("fp")   or "").upper()

        if form == "10-Q" and fp in ("Q1", "Q2", "Q3"):
            true_quarterly.append(item)
        elif form == "10-K" and fp == "FY":
            true_annual.append(item)
        # Vše ostatní (10-K/Q1-Q3 = YTD klouzavé součty) zahodíme

    # Seřaď sestupně
    true_quarterly.sort(key=lambda x: x.get("end", ""), reverse=True)
    true_annual.sort(key=lambda x: x.get("end", ""), reverse=True)

    # Deduplikuj quarterly
    seen = set()
    unique_q = []
    for q in true_quarterly:
        end = q.get("end")
        if end not in seen:
            seen.add(end)
            unique_q.append(q)

    # Pokud máme dost quarterly, použij je
    if len(unique_q) >= n:
        return [
            {"end": q["end"], "val": safe_float(q["val"])}
            for q in unique_q[:n]
            if safe_float(q.get("val")) is not None
        ]

    # Jinak doplň ročními (FY) záznamy — bez duplikátů
    combined = list(unique_q)
    for fy in true_annual:
        if fy.get("end") not in seen:
            seen.add(fy.get("end"))
            combined.append(fy)
        if len(combined) >= n:
            break

    combined.sort(key=lambda x: x.get("end", ""), reverse=True)

    return [
        {"end": item["end"], "val": safe_float(item["val"])}
        for item in combined[:n]
        if safe_float(item.get("val")) is not None
    ]


# =========================================================
# FLEXIBLE LOOKUP
# =========================================================

def pick_first_existing(section, candidates, n=4):
    for c in candidates:
        val = extract_time_series(section, c, n)
        if val:
            return val
    return []


def pick_latest_scalar(section, candidates):
    for c in candidates:
        val = extract_latest_value(section, c)
        if val is not None:
            return val
    return None


# =========================================================
# MAIN ENTRY
# =========================================================

def extract_fundamentals(data: dict) -> dict:
    facts = data.get("facts", {})

    gaap = facts.get("us-gaap", {}) or {}
    dei  = facts.get("dei", {}) or {}

    result = {}

    # ── Shares ───────────────────────────────────────────
    shares = pick_latest_scalar(gaap, [
        "EntityCommonStockSharesOutstanding",
        "CommonStockSharesOutstanding",
    ]) or pick_latest_scalar(dei, [
        "EntityCommonStockSharesOutstanding",
        "CommonStockSharesOutstanding",
    ])
    result["shares"] = shares

    # ── Časové řady ──────────────────────────────────────
    revenue_series = pick_first_existing(gaap, [
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "SalesRevenueNet",
    ])

    net_income_series = pick_first_existing(gaap, [
        "NetIncomeLoss",
        "ProfitLoss",
    ])

    operating_series = pick_first_existing(gaap, [
        "OperatingIncomeLoss",
    ])

    depreciation_series = pick_first_existing(gaap, [
        "DepreciationAndAmortization",
        "DepreciationDepletionAndAmortization",
    ])

    # ── Rozvaha (skaláry) ────────────────────────────────
    debt = pick_latest_scalar(gaap, [
        "LongTermDebt",
        "LongTermDebtAndCapitalLeaseObligations",
        "DebtCurrent",
    ])
    cash = pick_latest_scalar(gaap, [
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsAndShortTermInvestments",
    ])
    equity = pick_latest_scalar(gaap, [
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ])

    if debt  is not None: result["debt"]   = debt
    if cash  is not None: result["cash"]   = cash
    if equity is not None: result["equity"] = equity

    result["history"] = {
        "revenue":          revenue_series,
        "net_income":       net_income_series,
        "operating_income": operating_series,
        "depreciation":     depreciation_series,
    }

    # ── TTM ──────────────────────────────────────────────
    def compute_ttm(series):
        """
        TTM výpočet:
        - 4 quarterly záznamy (10-Q) → součet = TTM
        - 1 roční záznam (10-K/FY)   → přímo TTM
        - méně než 4 quarterly       → nejnovější jako proxy
        """
        if not series:
            return None

        if len(series) >= 4:
            vals = [x.get("val") for x in series[:4]]
            if any(v is None for v in vals):
                return None
            return sum(vals)

        # 1–3 záznamy: nejnovější jako proxy (pravděpodobně FY)
        return series[0].get("val")

    revenue_ttm    = compute_ttm(revenue_series)
    net_income_ttm = compute_ttm(net_income_series)

    if revenue_ttm    is not None: result["revenue"]    = revenue_ttm
    if net_income_ttm is not None: result["net_income"] = net_income_ttm

    # ── EBITDA margin pro valuation model ────────────────
    # Pokud máme operating income + depreciation, spočítáme EBITDA marži
    op_ttm  = compute_ttm(operating_series)
    dep_ttm = compute_ttm(depreciation_series)

    if op_ttm is not None and dep_ttm is not None and revenue_ttm:
        ebitda_ttm = op_ttm + dep_ttm
        result["ebitda"]        = ebitda_ttm
        result["ebitda_margin"] = ebitda_ttm / revenue_ttm

    return result
