"""
eu.py — EU / non-US fundamentals přes FMP
==========================================
Použití: akcie mimo US trhy (ticker nemá CIK v SEC EDGAR).

Cally na FMP (3 celkem):
  1. income-statement  → revenue, net income, EBITDA, operating income, D&A, EPS
  2. balance-sheet     → assets, equity, debt, cash, current items
  3. cash-flow         → CFO, CapEx → FCF

Výstup je identický se strukturou extract_fundamentals() z sec.py,
takže metrics.py, model.py a frontend fungují beze změny.

Ticker formát (FMP standard):
  ASML.AS   → Amsterdam (Euronext)
  SAP.XETRA → Frankfurt / XETRA
  MC.PA     → Paris (Euronext)
  AZN.L     → London Stock Exchange
  NESN.SW   → Swiss Exchange
"""

from __future__ import annotations
import math
from typing import Optional


# =========================================================
# UTIL
# =========================================================

def _f(x) -> Optional[float]:
    try:
        if x is None:
            return None
        if isinstance(x, str):
            x = x.replace(",", "")
        v = float(x)
        return None if (math.isnan(v) or math.isinf(v)) else v
    except Exception:
        return None


def _to_history(periods: list[dict], val_key: str) -> list[dict]:
    """
    Převede FMP periodická data na history formát:
    [{"end": "YYYY-MM-DD", "val": float}, ...]
    Nejnovější první, max 5 záznamů.
    """
    result = []
    for p in periods[:5]:
        date = p.get("date") or p.get("fillingDate") or p.get("acceptedDate", "")[:10]
        val  = _f(p.get(val_key))
        if date and val is not None:
            result.append({"end": date, "val": val})
    return result


def _compute_ttm(history: list[dict]) -> Optional[float]:
    """Součet posledních 4 quarterly záznamů = TTM."""
    vals = [q["val"] for q in history[:4] if q.get("val") is not None]
    if len(vals) == 4:
        return sum(vals)
    if len(vals) >= 1:
        return vals[0]   # fallback: poslední dostupná hodnota
    return None


# =========================================================
# FMP FETCH
# =========================================================

async def get_eu_fundamentals(
    client,
    ticker:      str,
    fmp_api_key: str,
    safe_get,           # předáme safe_get z main.py
    limit:       int = 5,
) -> dict | None:
    """
    Stáhne fundamentals z FMP pro EU/non-US ticker.
    Vrátí dict kompatibilní s extract_fundamentals() ze sec.py.

    Parametry:
      ticker      — FMP formát (ASML.AS, SAP.XETRA, MC.PA, ...)
      fmp_api_key — FMP API klíč z env
      safe_get    — async helper z main.py
      limit       — počet quarterly period (default 5)
    """
    if not fmp_api_key:
        return None

    FMP = "https://financialmodelingprep.com/stable"
    params_q = {"symbol": ticker, "period": "quarter", "limit": limit, "apikey": fmp_api_key}
    params_a = {"symbol": ticker, "period": "annual",  "limit": 2,     "apikey": fmp_api_key}

    try:
        # Paralelní fetch — 3 cally
        import asyncio
        income_q, balance_q, cashflow_q = await asyncio.gather(
            safe_get(client, f"{FMP}/income-statement",        params_q),
            safe_get(client, f"{FMP}/balance-sheet-statement", params_q),
            safe_get(client, f"{FMP}/cash-flow-statement",     params_q),
        )
    except Exception as e:
        print(f"[eu_fundamentals] {ticker} fetch error: {repr(e)}")
        return None

    if not income_q:
        print(f"[eu_fundamentals] {ticker}: žádná income data")
        return None

    # ── Nejnovější rozvaha (point-in-time skaláry) ───────
    bal = (balance_q or [{}])[0]
    cf  = (cashflow_q or [{}])

    equity      = _f(bal.get("totalStockholdersEquity"))
    total_assets = _f(bal.get("totalAssets"))
    debt        = _f(bal.get("totalDebt")) or 0
    cash        = _f(bal.get("cashAndCashEquivalents")) or 0
    cur_assets  = _f(bal.get("totalCurrentAssets"))
    cur_liab    = _f(bal.get("totalCurrentLiabilities"))

    # ── Shares (z nejnovějšího income záznamu) ───────────
    inc0   = income_q[0] if income_q else {}
    shares = _f(inc0.get("weightedAverageShsOutDil")) or _f(inc0.get("weightedAverageShsOut"))

    # ── History (quarterly série) ─────────────────────────
    rev_history = _to_history(income_q, "revenue")
    ni_history  = _to_history(income_q, "netIncome")
    op_history  = _to_history(income_q, "operatingIncome")
    dep_history = _to_history(income_q, "depreciationAndAmortization")

    # ── TTM výpočty ───────────────────────────────────────
    revenue_ttm    = _compute_ttm(rev_history)
    net_income_ttm = _compute_ttm(ni_history)
    op_ttm         = _compute_ttm(op_history)
    dep_ttm        = _compute_ttm(dep_history)

    # EBITDA = operating income + D&A (nebo přímý field)
    ebitda_history = _to_history(income_q, "ebitda")
    ebitda_ttm     = _compute_ttm(ebitda_history)
    if ebitda_ttm is None and op_ttm is not None and dep_ttm is not None:
        ebitda_ttm = op_ttm + dep_ttm

    ebitda_margin = (ebitda_ttm / revenue_ttm) if (ebitda_ttm and revenue_ttm) else None

    # ── FCF z cash flow ───────────────────────────────────
    fcf_history  = _to_history(cf, "freeCashFlow")
    fcf_ttm      = _compute_ttm(fcf_history)
    # Pokud FMP nemá přímý freeCashFlow, dopočítej z CFO − CapEx
    if fcf_ttm is None:
        cfo_history  = _to_history(cf, "operatingCashFlow")
        capex_history = _to_history(cf, "capitalExpenditure")
        cfo_ttm   = _compute_ttm(cfo_history)
        capex_ttm = _compute_ttm(capex_history)
        if cfo_ttm is not None and capex_ttm is not None:
            fcf_ttm = cfo_ttm - abs(capex_ttm)

    # ── Derived metriky ───────────────────────────────────
    net_debt      = debt - cash
    current_ratio = (cur_assets / cur_liab) if (cur_assets and cur_liab and cur_liab != 0) else None

    # ROE / ROA z TTM
    roe = (net_income_ttm / equity)       if (net_income_ttm and equity and equity > 0) else None
    roa = (net_income_ttm / total_assets) if (net_income_ttm and total_assets and total_assets != 0) else None

    # Dividendy — FMP vrací DPS v income statement
    dps = _f(inc0.get("dividendsPerSharePaid")) or _f(inc0.get("dividendsPerShareDeclared"))

    # Tax rate
    tax_expense = _f(inc0.get("incomeTaxExpense"))
    pretax      = _f(inc0.get("incomeBeforeTax"))
    tax_rate    = None
    if tax_expense is not None and pretax and pretax != 0:
        rate = tax_expense / pretax
        tax_rate = rate if 0 <= rate <= 0.6 else None

    # EPS quarterly
    eps_quarterly = []
    if shares and shares > 0:
        for q in ni_history[:4]:
            if q.get("val") is not None:
                eps_quarterly.append({"end": q["end"], "eps": q["val"] / shares})

    # ── Výsledný dict (kompatibilní se sec.py) ────────────
    result: dict = {
        "source":    "fmp_eu",
        "confidence": 0.7,
    }

    if shares        is not None: result["shares"]         = shares
    if equity        is not None: result["equity"]         = equity
    if total_assets  is not None: result["total_assets"]   = total_assets
    if cur_assets    is not None: result["current_assets"] = cur_assets
    if cur_liab      is not None: result["current_liabilities"] = cur_liab
    if current_ratio is not None: result["current_ratio"]  = current_ratio
    if roe           is not None: result["roe"]            = roe
    if roa           is not None: result["roa"]            = roa
    if dps           is not None: result["dps"]            = dps
    if tax_rate      is not None: result["tax_rate"]       = tax_rate
    if fcf_ttm       is not None: result["fcf"]            = fcf_ttm
    if ebitda_margin is not None: result["ebitda_margin"]  = ebitda_margin
    if eps_quarterly:             result["eps_quarterly"]  = eps_quarterly

    result["debt"]     = debt
    result["cash"]     = cash
    result["net_debt"] = net_debt

    if revenue_ttm    is not None: result["revenue"]    = revenue_ttm
    if net_income_ttm is not None: result["net_income"] = net_income_ttm
    if ebitda_ttm     is not None: result["ebitda"]     = ebitda_ttm

    result["history"] = {
        "revenue":          rev_history,
        "net_income":       ni_history,
        "operating_income": op_history,
        "depreciation":     dep_history,
    }

    print(f"[eu_fundamentals] {ticker} | revenue={revenue_ttm} | net_income={net_income_ttm} | fcf={fcf_ttm}")
    return result


# =========================================================
# DETEKCE US vs EU
# =========================================================

def is_us_ticker(ticker: str, cik_map: dict) -> bool:
    """
    Vrátí True pokud ticker existuje v SEC CIK mapě = US akcie.
    False = EU/non-US → použij eu.py pipeline.

    EU tickery typicky obsahují tečku s exchange suffix:
      ASML.AS, SAP.XETRA, MC.PA, AZN.L ...
    US tickery jsou bez tečky nebo s .US:
      AAPL, MSFT, NVDA, PFE ...
    """
    # Přímý lookup v CIK mapě (nejspolehlivější)
    base = ticker.upper().split(".")[0]
    if cik_map.get(ticker.upper()) or cik_map.get(base):
        return True

    # Ticker s exchange suffix = EU
    if "." in ticker:
        return False

    return False   # fallback: bez CIK = neznámý → zkus EU pipeline
