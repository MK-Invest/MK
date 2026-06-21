"""
backend/sec/metrics.py — odvozené metriky z kvartálních/ročních časových řad:
TTM součty, 5Y CAGR, medián FCF.
"""

import datetime
import statistics


def compute_ttm(series, annual_series=None):
    """
    TTM (trailing twelve months) součet ze 4 nejnovějších kvartálů.

    annual_series je FALLBACK — pokud nemáme kompletní sadu 4 čistých
    kvartálů (mezera v SEC podáních, firma po spin-offu jako 3M), použije
    se nejnovější celoroční (10-K/20-F) hodnota místo vrácení None.
    Bez tohoto fallbacku celý valuation model spadne na chybějících datech
    i když existuje naprosto použitelné roční číslo.
    """
    if series and len(series) >= 4:
        vals = [x["val"] for x in series[:4] if x.get("val") is not None]
        if len(vals) == 4:
            return sum(vals)

    if annual_series:
        return sorted(annual_series, key=lambda x: x["end"], reverse=True)[0]["val"]

    if series and len(series) == 1:
        return series[0]["val"]

    return None


def compute_cagr_5y(series):
    """
    Spočítá 5Y CAGR z quarterly série (DESC pořadí, nejnovější první).
    Hledá hodnotu před ~5 lety (20 kvartálů zpět, nebo nejbližší dostupnou).
    Vrátí None pokud nemáme dostatek dat nebo výsledek je nesmyslný.
    """
    if not series or len(series) < 8:
        return None

    newest = series[0].get("val")
    if not newest or newest <= 0:
        return None

    target_idx = min(19, len(series) - 1)
    oldest = series[target_idx].get("val")
    if not oldest or oldest <= 0:
        return None

    try:
        date_new = datetime.date.fromisoformat(series[0]["end"])
        date_old = datetime.date.fromisoformat(series[target_idx]["end"])
        years = (date_new - date_old).days / 365.25
        if years < 1:
            return None
    except Exception:
        years = target_idx / 4

    cagr = (newest / oldest) ** (1 / years) - 1

    # Sanitace — CAGR mimo -50 % až +100 % je podezřelý (data error,
    # nebo srovnání přes velkou korporátní restrukturalizaci)
    if not (-0.50 <= cagr <= 1.00):
        return None

    return cagr


def compute_fcf_median(fcf_history):
    """
    Medián z roční FCF historie — robustní vůči jednorázovým výkyvům
    (COVID windfall rok, akviziční dluh), na rozdíl od průměru.
    """
    values = [x["fcf"] for x in fcf_history if x.get("fcf") is not None]
    if not values:
        return None
    return statistics.median(values)
