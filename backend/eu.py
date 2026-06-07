"""
eu.py — EU / non-US fundamentals přes yfinance
================================================
Použití: akcie mimo US trhy (ticker nemá CIK v SEC EDGAR).

yfinance je zdarma, bez API klíče, pokrývá EU burzy.
Ticker formát:
  ASML.AS   → Amsterdam (Euronext)
  SAP.XETRA → Frankfurt / XETRA (nebo SAP.DE)
  MC.PA     → Paris (Euronext)
  AZN.L     → London Stock Exchange
  NESN.SW   → Swiss Exchange
  AIR.PA    → Airbus, Paris

Výstup je identický se strukturou extract_fundamentals() z sec.py,
takže metrics.py, model.py a frontend fungují beze změny.

Instalace: pip install yfinance
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
        v = float(x)
        return None if (math.isnan(v) or math.isinf(v)) else v
    except Exception:
        return None


def _to_history(df, col: str, n: int = 5) -> list[dict]:
    """
    Převede pandas DataFrame (quarterly financials) na history formát.
    df.columns = DatetimeIndex (nejnovější první nebo vzestupně)
    Vrátí [{"end": "YYYY-MM-DD", "val": float}, ...] nejnovější první.
    """
    if df is None or col not in df.index:
        return []

    row = df.loc[col]
    result = []

    for date, val in row.items():
        v = _f(val)
        if v is not None:
            try:
                date_str = str(date)[:10]
                result.append({"end": date_str, "val": v})
            except Exception:
                continue

    # Seřaď nejnovější první
    result.sort(key=lambda x: x["end"], reverse=True)
    return result[:n]


def _ttm(history: list[dict]) -> Optional[float]:
    """Součet posledních 4 quarterly záznamů = TTM."""
    vals = [q["val"] for q in history[:4] if q.get("val") is not None]
    if len(vals) == 4:
        return sum(vals)
    if vals:
        return vals[0]  # fallback
    return None


# =========================================================
# YFINANCE FETCH (synchronní — spouští se v executor)
# =========================================================

def _fetch_yfinance(ticker: str) -> dict | None:
    """
    Synchronní fetch přes yfinance.
    Volá se z asyncio přes run_in_executor aby neblokoval event loop.
    """
    try:
        import yfinance as yf
    except ImportError:
        print("[eu] yfinance není nainstalováno — spusť: pip install yfinance")
        return None

    try:
        t = yf.Ticker(ticker)

        # ── Info (skaláry) ───────────────────────────────
        info = t.info or {}

        shares      = _f(info.get("sharesOutstanding"))
        equity      = _f(info.get("bookValue"))
        total_assets = None   # yfinance info nemá přímo, vezme z balance sheet
        cur_ratio   = _f(info.get("currentRatio"))
        debt        = _f(info.get("totalDebt")) or 0
        cash        = _f(info.get("totalCash")) or 0
        dps         = _f(info.get("dividendRate"))   # roční dividenda na akcii
        beta        = _f(info.get("beta"))

        # ── Quarterly financials ─────────────────────────
        try:
            inc_q  = t.quarterly_income_stmt    # income statement quarterly
        except Exception:
            inc_q = None

        try:
            bal_q  = t.quarterly_balance_sheet
        except Exception:
            bal_q = None

        try:
            cf_q   = t.quarterly_cashflow
        except Exception:
            cf_q = None

        # ── Revenue history ──────────────────────────────
        rev_history = _to_history(inc_q, "Total Revenue")
        if not rev_history:
            rev_history = _to_history(inc_q, "Operating Revenue")

        # ── Net Income history ───────────────────────────
        ni_history = _to_history(inc_q, "Net Income")

        # ── Operating Income history ─────────────────────
        op_history = _to_history(inc_q, "Operating Income")
        if not op_history:
            op_history = _to_history(inc_q, "EBIT")

        # ── D&A history ──────────────────────────────────
        dep_history = _to_history(cf_q, "Depreciation And Amortization")
        if not dep_history:
            dep_history = _to_history(inc_q, "Reconciled Depreciation")

        # ── TTM výpočty ──────────────────────────────────
        revenue_ttm    = _ttm(rev_history)
        net_income_ttm = _ttm(ni_history)
        op_ttm         = _ttm(op_history)
        dep_ttm        = _ttm(dep_history)

        # EBITDA
        ebitda_history = _to_history(inc_q, "EBITDA")
        ebitda_ttm     = _ttm(ebitda_history)
        if ebitda_ttm is None and op_ttm is not None and dep_ttm is not None:
            ebitda_ttm = op_ttm + dep_ttm

        ebitda_margin = (ebitda_ttm / revenue_ttm) if (ebitda_ttm and revenue_ttm) else None

        # ── FCF ──────────────────────────────────────────
        fcf_history = _to_history(cf_q, "Free Cash Flow")
        fcf_ttm     = _ttm(fcf_history)
        if fcf_ttm is None:
            cfo_h   = _to_history(cf_q, "Operating Cash Flow")
            capex_h = _to_history(cf_q, "Capital Expenditure")
            cfo     = _ttm(cfo_h)
            capex   = _ttm(capex_h)
            if cfo is not None and capex is not None:
                fcf_ttm = cfo - abs(capex)

        # ── Rozvaha — nejnovější snapshot ────────────────
        if bal_q is not None and not bal_q.empty:
            latest_bal = bal_q.iloc[:, 0]   # nejnovější sloupec
            total_assets   = _f(latest_bal.get("Total Assets"))
            cur_assets     = _f(latest_bal.get("Current Assets"))
            cur_liab       = _f(latest_bal.get("Current Liabilities"))
            equity_bal     = _f(latest_bal.get("Stockholders Equity")) or \
                             _f(latest_bal.get("Common Stock Equity"))
            if equity_bal:
                equity = equity_bal
            if cur_assets and cur_liab and cur_liab != 0:
                cur_ratio = cur_assets / cur_liab
        else:
            cur_assets = None
            cur_liab   = None

        # ── Derived metriky ──────────────────────────────
        net_debt  = debt - cash
        roe = (net_income_ttm / equity)       if (net_income_ttm and equity and equity > 0) else None
        roa = (net_income_ttm / total_assets) if (net_income_ttm and total_assets and total_assets != 0) else None

        # Tax rate z info nebo z income stmt
        tax_rate = None
        if inc_q is not None:
            tax_h = _to_history(inc_q, "Tax Provision")
            pre_h = _to_history(inc_q, "Pretax Income")
            t_ttm = _ttm(tax_h)
            p_ttm = _ttm(pre_h)
            if t_ttm and p_ttm and p_ttm != 0:
                rate = t_ttm / p_ttm
                tax_rate = rate if 0 <= rate <= 0.6 else None

        # EPS quarterly
        eps_quarterly = []
        if shares and shares > 0:
            for q in ni_history[:4]:
                if q.get("val") is not None:
                    eps_quarterly.append({"end": q["end"], "eps": q["val"] / shares})

        # ── Výsledný dict (kompatibilní se sec.py) ───────
        result: dict = {
            "source":     "yfinance",
            "confidence": 0.65,
        }

        if shares        is not None: result["shares"]         = shares
        if equity        is not None: result["equity"]         = equity
        if total_assets  is not None: result["total_assets"]   = total_assets
        if cur_assets    is not None: result["current_assets"] = cur_assets
        if cur_liab      is not None: result["current_liabilities"] = cur_liab
        if cur_ratio     is not None: result["current_ratio"]  = cur_ratio
        if roe           is not None: result["roe"]            = roe
        if roa           is not None: result["roa"]            = roa
        if dps           is not None: result["dps"]            = dps
        if tax_rate      is not None: result["tax_rate"]       = tax_rate
        if fcf_ttm       is not None: result["fcf"]            = fcf_ttm
        if ebitda_margin is not None: result["ebitda_margin"]  = ebitda_margin
        if beta          is not None: result["beta"]           = beta
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

        print(f"[eu_yfinance] {ticker} | revenue={revenue_ttm} | net_income={net_income_ttm} | fcf={fcf_ttm}")
        return result

    except Exception as e:
        print(f"[eu_yfinance] {ticker} error: {repr(e)}")
        return None


# =========================================================
# ASYNC WRAPPER
# =========================================================

async def get_eu_fundamentals(ticker: str) -> dict | None:
    """
    Async wrapper — spouští synchronní yfinance v thread executoru
    aby neblokoval FastAPI event loop.
    """
    import asyncio
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _fetch_yfinance, ticker)


# =========================================================
# DETEKCE US vs EU
# =========================================================

def is_us_ticker(ticker: str, cik_map: dict) -> bool:
    """
    True  = US akcie → SEC pipeline
    False = EU/non-US → yfinance pipeline

    Logika:
    1. Ticker s tečkou (ASML.AS, SAP.DE) → vždy EU
    2. Ticker bez tečky → hledej v SEC CIK mapě
    3. Pokud není v CIK mapě → EU pipeline
    """
    if "." in ticker:
        return False

    base = ticker.upper()
    return bool(cik_map.get(base))
