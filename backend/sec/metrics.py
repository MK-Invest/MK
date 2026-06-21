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


def compute_cagr(series, target_years=5, min_quarters=8):
    """
    Obecná CAGR funkce s parametrizovatelným oknem.

    Spočítá CAGR z quarterly série (DESC pořadí, nejnovější první).
    Hledá hodnotu před ~target_years lety (target_years*4 kvartálů zpět,
    nebo nejbližší dostupnou). Vrátí None pokud nemáme dostatek dat
    nebo výsledek je nesmyslný.

    Kratší okno (např. target_years=2) je užitečné pro firmy po velké
    restrukturalizaci/spin-offu, kde 5Y okno spadá doprostřed starého
    poklesu a dá zavádějící číslo i když posledních pár kvartálů firma
    už zrychluje.
    """
    if not series or len(series) < min_quarters:
        return None

    newest = series[0].get("val")
    if not newest or newest <= 0:
        return None

    target_idx = min(target_years * 4 - 1, len(series) - 1)
    oldest = series[target_idx].get("val")
    if not oldest or oldest <= 0:
        return None

    try:
        date_new = datetime.date.fromisoformat(series[0]["end"])
        date_old = datetime.date.fromisoformat(series[target_idx]["end"])
        years = (date_new - date_old).days / 365.25
        if years < 0.5:
            return None
    except Exception:
        years = target_idx / 4

    cagr = (newest / oldest) ** (1 / years) - 1

    # Sanitace — CAGR mimo -50 % až +100 % je podezřelý (data error,
    # nebo srovnání přes velkou korporátní restrukturalizaci)
    if not (-0.50 <= cagr <= 1.00):
        return None

    return cagr


def compute_cagr_5y(series):
    """5Y CAGR — zpětně kompatibilní wrapper kolem compute_cagr()."""
    return compute_cagr(series, target_years=5, min_quarters=8)


def compute_cagr_2y(series):
    """
    2Y CAGR — krátké okno pro EPS/FCF trend. Méně náchylné na zkreslení
    starou restrukturalizací/spin-offem než 5Y okno, ale pořád dost dlouhé
    na to, aby vyhladilo kvartální šum (na rozdíl od QoQ srovnání).
    """
    return compute_cagr(series, target_years=2, min_quarters=4)


def compute_fcf_median(fcf_history):
    """
    Medián z roční FCF historie — robustní vůči jednorázovým výkyvům
    (COVID windfall rok, akviziční dluh), na rozdíl od průměru.
    """
    values = [x["fcf"] for x in fcf_history if x.get("fcf") is not None]
    if not values:
        return None
    return statistics.median(values)
