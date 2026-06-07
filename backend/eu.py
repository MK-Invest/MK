"""
eu.py — EU / non-US pipeline přes yfinance
===========================================
Pokrývá cenu, OHLCV i fundamentals pro non-US tickery.
TwelveData free tier EU akcie nepodporuje → yfinance je jediná
spolehlivá free volba.

Ticker formát (Yahoo Finance standard):
  ASML.AS   → Amsterdam
  SAP.DE    → Frankfurt XETRA
  MC.PA     → Paris
  AZN.L     → London
  NESN.SW   → Swiss
"""

from __future__ import annotations
import math
from typing import Optional


def _f(x) -> Optional[float]:
    try:
        if x is None:
            return None
        v = float(x)
        return None if (math.isnan(v) or math.isinf(v)) else v
    except Exception:
        return None


def _to_history(df, col: str, n: int = 5) -> list[dict]:
    if df is None or col not in df.index:
        return []
    row = df.loc[col]
    result = []
    for date, val in row.items():
        v = _f(val)
        if v is not None:
            try:
                result.append({"end": str(date)[:10], "val": v})
            except Exception:
                continue
    result.sort(key=lambda x: x["end"], reverse=True)
    return result[:n]


def _ttm(history: list[dict]) -> Optional[float]:
    vals = [q["val"] for q in history[:4] if q.get("val") is not None]
    if len(vals) == 4:
        return sum(vals)
    if vals:
        return vals[0]
    return None


def _fetch_yfinance(ticker: str) -> dict | None:
    """
    Synchronní fetch přes yfinance — cena + OHLCV + fundamentals.
    Spouští se v thread executor aby neblokoval event loop.
    """
    try:
        import yfinance as yf
    except ImportError:
        print("[eu] Nainstaluj yfinance: pip install yfinance")
        return None

    try:
        t = yf.Ticker(ticker)
        info = t.info or {}

        # ── Cena ─────────────────────────────────────────
        price = (
            _f(info.get("currentPrice"))
            or _f(info.get("regularMarketPrice"))
            or _f(info.get("previousClose"))
        )

        # ── OHLCV (200 obchodních dní) ────────────────────
        hist_df = t.history(period="200d")
        ohlcv = []
        if hist_df is not None and not hist_df.empty:
            for date, row in hist_df.iloc[::-1].iterrows():  # nejnovější první
                ohlcv.append({
                    "datetime": str(date)[:10],
                    "open":     str(row.get("Open",  0)),
                    "high":     str(row.get("High",  0)),
                    "low":      str(row.get("Low",   0)),
                    "close":    str(row.get("Close", 0)),
                    "volume":   str(int(row.get("Volume", 0))),
                })

        # ── Skaláry z info ────────────────────────────────
        shares       = _f(info.get("sharesOutstanding"))
        debt         = _f(info.get("totalDebt"))        or 0
        cash         = _f(info.get("totalCash"))        or 0
        cur_ratio    = _f(info.get("currentRatio"))
        dps          = _f(info.get("dividendRate"))
        beta         = _f(info.get("beta"))
        name         = info.get("longName") or info.get("shortName") or ticker

        # ── Quarterly financials ──────────────────────────
        try:
            inc_q = t.quarterly_income_stmt
        except Exception:
            inc_q = None
        try:
            bal_q = t.quarterly_balance_sheet
        except Exception:
            bal_q = None
        try:
            cf_q = t.quarterly_cashflow
        except Exception:
            cf_q = None

        # ── History série ─────────────────────────────────
        rev_history = _to_history(inc_q, "Total Revenue") or _to_history(inc_q, "Operating Revenue")
        ni_history  = _to_history(inc_q, "Net Income")
        op_history  = _to_history(inc_q, "Operating Income") or _to_history(inc_q, "EBIT")
        dep_history = _to_history(cf_q,  "Depreciation And Amortization") or \
                      _to_history(inc_q, "Reconciled Depreciation")

        # ── TTM ───────────────────────────────────────────
        revenue_ttm    = _ttm(rev_history)
        net_income_ttm = _ttm(ni_history)
        op_ttm         = _ttm(op_history)
        dep_ttm        = _ttm(dep_history)

        ebitda_history = _to_history(inc_q, "EBITDA")
        ebitda_ttm     = _ttm(ebitda_history)
        if ebitda_ttm is None and op_ttm is not None and dep_ttm is not None:
            ebitda_ttm = op_ttm + dep_ttm
        ebitda_margin = (ebitda_ttm / revenue_ttm) if (ebitda_ttm and revenue_ttm) else None

        fcf_history = _to_history(cf_q, "Free Cash Flow")
        fcf_ttm     = _ttm(fcf_history)
        if fcf_ttm is None:
            cfo   = _ttm(_to_history(cf_q, "Operating Cash Flow"))
            capex = _ttm(_to_history(cf_q, "Capital Expenditure"))
            if cfo is not None and capex is not None:
                fcf_ttm = cfo - abs(capex)

        # ── Rozvaha snapshot ──────────────────────────────
        total_assets = None
        cur_assets   = None
        cur_liab     = None
        equity       = None

        if bal_q is not None and not bal_q.empty:
            lb = bal_q.iloc[:, 0]
            total_assets = _f(lb.get("Total Assets"))
            cur_assets   = _f(lb.get("Current Assets"))
            cur_liab     = _f(lb.get("Current Liabilities"))
            equity       = _f(lb.get("Stockholders Equity")) or \
                           _f(lb.get("Common Stock Equity"))
            if cur_assets and cur_liab and cur_liab != 0:
                cur_ratio = cur_assets / cur_liab

        # ── Derived ───────────────────────────────────────
        net_debt = debt - cash
        roe = (net_income_ttm / equity)       if (net_income_ttm and equity and equity > 0) else None
        roa = (net_income_ttm / total_assets) if (net_income_ttm and total_assets and total_assets != 0) else None

        tax_rate = None
        if inc_q is not None:
            t_ttm = _ttm(_to_history(inc_q, "Tax Provision"))
            p_ttm = _ttm(_to_history(inc_q, "Pretax Income"))
            if t_ttm and p_ttm and p_ttm != 0:
                rate = t_ttm / p_ttm
                tax_rate = rate if 0 <= rate <= 0.6 else None

        eps_quarterly = []
        if shares and shares > 0:
            for q in ni_history[:4]:
                if q.get("val") is not None:
                    eps_quarterly.append({"end": q["end"], "eps": q["val"] / shares})

        # ── Výsledek ──────────────────────────────────────
        result: dict = {
            "source":     "yfinance",
            "confidence": 0.65,
            "name":       name,
            "price":      price,
            "ohlcv":      ohlcv,
            "debt":       debt,
            "cash":       cash,
            "net_debt":   net_debt,
        }

        if shares        is not None: result["shares"]              = shares
        if equity        is not None: result["equity"]              = equity
        if total_assets  is not None: result["total_assets"]        = total_assets
        if cur_assets    is not None: result["current_assets"]      = cur_assets
        if cur_liab      is not None: result["current_liabilities"] = cur_liab
        if cur_ratio     is not None: result["current_ratio"]       = cur_ratio
        if roe           is not None: result["roe"]                 = roe
        if roa           is not None: result["roa"]                 = roa
        if dps           is not None: result["dps"]                 = dps
        if tax_rate      is not None: result["tax_rate"]            = tax_rate
        if fcf_ttm       is not None: result["fcf"]                 = fcf_ttm
        if ebitda_margin is not None: result["ebitda_margin"]       = ebitda_margin
        if beta          is not None: result["beta"]                = beta
        if eps_quarterly:             result["eps_quarterly"]       = eps_quarterly
        if revenue_ttm   is not None: result["revenue"]             = revenue_ttm
        if net_income_ttm is not None: result["net_income"]         = net_income_ttm
        if ebitda_ttm    is not None: result["ebitda"]              = ebitda_ttm

        result["history"] = {
            "revenue":          rev_history,
            "net_income":       ni_history,
            "operating_income": op_history,
            "depreciation":     dep_history,
        }

        print(f"[eu_yfinance] {ticker} | price={price} | revenue={revenue_ttm} | fcf={fcf_ttm}")
        return result

    except Exception as e:
        print(f"[eu_yfinance] {ticker} error: {repr(e)}")
        return None


async def get_eu_fundamentals(ticker: str) -> dict | None:
    """Async wrapper — yfinance v thread executoru."""
    import asyncio
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _fetch_yfinance, ticker)


def is_us_ticker(ticker: str, cik_map: dict) -> bool:
    """True = US (SEC pipeline), False = EU/non-US (yfinance pipeline)."""
    if "." in ticker:
        return False
    return bool(cik_map.get(ticker.upper()))
