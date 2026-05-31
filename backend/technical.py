"""
technical.py — Technická analýza z OHLCV dat
=============================================
RSI, MA, SMA — denní svíčky (200 dní)
Demand/Supply zóny — týdenní svíčky (resampleované z denních)
  Zóna = rozsah low–high swingové svíčky
"""

from __future__ import annotations
import math
from typing import Optional


# =========================================================
# UTIL
# =========================================================

def _f(x) -> Optional[float]:
    try:
        v = float(x)
        return None if (math.isnan(v) or math.isinf(v)) else v
    except Exception:
        return None


def _parse_ohlcv(raw: list[dict]) -> list[dict]:
    """
    Převede raw TwelveData záznamy na čisté floaty.
    Vstup nejnovější první → obrátíme na chronologické pořadí.
    """
    parsed = []
    for r in reversed(raw):
        o = _f(r.get("open"))
        h = _f(r.get("high"))
        l = _f(r.get("low"))
        c = _f(r.get("close"))
        v = _f(r.get("volume"))
        if None not in (o, h, l, c):
            parsed.append({
                "date":   r.get("datetime", ""),
                "open":   o,
                "high":   h,
                "low":    l,
                "close":  c,
                "volume": v or 0.0,
            })
    return parsed


# =========================================================
# WEEKLY RESAMPLE
# =========================================================

def _resample_weekly(candles: list[dict]) -> list[dict]:
    """
    Resampleuje denní OHLCV na týdenní svíčky (pondělí–pátek).
    Vstup musí být chronologicky vzestupně (nejstarší první).

    Každá týdenní svíčka:
      open   = open prvního dne týdne
      high   = max(high) za celý týden
      low    = min(low)  za celý týden
      close  = close posledního dne týdne
      volume = součet volume
      date   = datum posledního dne (pátek nebo poslední obchodní den)
    """
    from datetime import date as _date

    if not candles:
        return []

    def week_key(date_str: str) -> str:
        """ISO rok-týden jako klíč skupiny."""
        try:
            d = _date.fromisoformat(date_str)
            iso = d.isocalendar()
            return f"{iso[0]}-W{iso[1]:02d}"
        except Exception:
            return date_str[:7]   # fallback: YYYY-MM

    from collections import OrderedDict
    weeks: OrderedDict = OrderedDict()

    for c in candles:
        wk = week_key(c["date"])
        if wk not in weeks:
            weeks[wk] = {
                "date":   c["date"],
                "open":   c["open"],
                "high":   c["high"],
                "low":    c["low"],
                "close":  c["close"],
                "volume": c["volume"],
            }
        else:
            w = weeks[wk]
            w["high"]   = max(w["high"],   c["high"])
            w["low"]    = min(w["low"],    c["low"])
            w["close"]  = c["close"]       # poslední close týdne
            w["volume"] += c["volume"]
            w["date"]   = c["date"]        # poslední datum týdne

    return list(weeks.values())


# =========================================================
# RSI
# =========================================================

def compute_rsi(candles: list[dict], period: int = 14) -> Optional[float]:
    """
    Wilderův RSI — stejný jako TradingView a Yahoo Finance.
    """
    closes = [c["close"] for c in candles]
    if len(closes) < period + 1:
        return None

    changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]

    gains  = [max(c, 0)  for c in changes[:period]]
    losses = [abs(min(c, 0)) for c in changes[:period]]
    avg_gain = sum(gains)  / period
    avg_loss = sum(losses) / period

    for change in changes[period:]:
        avg_gain = (avg_gain * (period - 1) + max(change, 0))       / period
        avg_loss = (avg_loss * (period - 1) + abs(min(change, 0))) / period

    if avg_loss == 0:
        return 100.0

    rs  = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)


# =========================================================
# MOVING AVERAGES
# =========================================================

def compute_sma(candles: list[dict], period: int) -> Optional[float]:
    closes = [c["close"] for c in candles]
    if len(closes) < period:
        return None
    return round(sum(closes[-period:]) / period, 4)


def compute_ema(candles: list[dict], period: int) -> Optional[float]:
    closes = [c["close"] for c in candles]
    if len(closes) < period:
        return None

    k   = 2 / (period + 1)
    ema = sum(closes[:period]) / period

    for price in closes[period:]:
        ema = price * k + ema * (1 - k)

    return round(ema, 4)


# =========================================================
# SWING DETECTION (pro týdenní svíčky)
# =========================================================

def _week_key(date_str: str) -> str:
    """ISO rok-týden jako klíč."""
    from datetime import date as _date
    try:
        d = _date.fromisoformat(date_str)
        iso = d.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    except Exception:
        return date_str[:7]


def _find_swings(
    weekly: list[dict],
    daily:  list[dict],
    lookback: int = 3,
) -> tuple[list, list]:
    """
    Swing lows na týdenních svíčkách, zóny zpřesněné denními daty.

    Podmínka swing low:
      - weekly[i].low je nejnižší v okně ±lookback
      - weekly[i-1].low >= weekly[i].low  (předchozí týden nesmí mít nižší low)

    Zóna demand:
      zone_low  = low  denní svíčky s nejnižším low v daném týdnu
      zone_high = high TÉ SAMÉ denní svíčky (ne nejvyšší high týdne)

    Podmínka swing high (symetricky):
      - weekly[i].high je nejvyšší v okně ±lookback
      - weekly[i-1].high <= weekly[i].high

    Zóna supply:
      zone_low  = low  denní svíčky s nejvyšším high v daném týdnu
      zone_high = high TÉ SAMÉ denní svíčky
    """
    from collections import defaultdict

    # Seskup denní svíčky podle ISO týdne
    daily_by_week: dict = defaultdict(list)
    for c in daily:
        daily_by_week[_week_key(c["date"])].append(c)

    n = len(weekly)
    swing_lows  = []
    swing_highs = []

    for i in range(lookback, n - lookback):
        window_highs = [weekly[j]["high"] for j in range(i - lookback, i + lookback + 1) if j != i]
        window_lows  = [weekly[j]["low"]  for j in range(i - lookback, i + lookback + 1) if j != i]

        w    = weekly[i]
        prev = weekly[i - 1]
        wk   = _week_key(w["date"])
        day_candles = daily_by_week.get(wk, [])

        # ── Swing low ────────────────────────────────────
        # Podmínky: nejnižší low v okně + předchozí týden nesmí mít nižší low
        if w["low"] < min(window_lows) and prev["low"] >= w["low"]:
            future_closes = [weekly[j]["close"] for j in range(i + 1, min(i + lookback + 1, n))]
            strength = (max(future_closes) - w["low"]) / w["low"] if future_closes else 0.0

            if day_candles:
                # Denní svíčka s nejnižším low toho týdne
                anchor   = min(day_candles, key=lambda c: c["low"])
                zone_lo  = anchor["low"]   # low ankrové svíčky
                zone_hi  = anchor["high"]  # high TÉ SAMÉ svíčky
            else:
                zone_lo = w["low"]
                zone_hi = w["high"]

            swing_lows.append({
                "idx":         i,
                "date":        w["date"],
                "price":       w["low"],
                "candle_low":  zone_lo,
                "candle_high": zone_hi,
                "strength":    round(strength, 4),
                "volume":      w["volume"],
            })

        # ── Swing high ───────────────────────────────────
        # Podmínky: nejvyšší high v okně + předchozí týden nesmí mít vyšší high
        if w["high"] > max(window_highs) and prev["high"] <= w["high"]:
            future_closes = [weekly[j]["close"] for j in range(i + 1, min(i + lookback + 1, n))]
            strength = (w["high"] - min(future_closes)) / w["high"] if future_closes else 0.0

            if day_candles:
                # Denní svíčka s nejvyšším high toho týdne
                anchor   = max(day_candles, key=lambda c: c["high"])
                zone_lo  = anchor["low"]   # low ankrové svíčky
                zone_hi  = anchor["high"]  # high TÉ SAMÉ svíčky
            else:
                zone_lo = w["low"]
                zone_hi = w["high"]

            swing_highs.append({
                "idx":         i,
                "date":        w["date"],
                "price":       w["high"],
                "candle_low":  zone_lo,
                "candle_high": zone_hi,
                "strength":    round(strength, 4),
                "volume":      w["volume"],
            })

    return swing_lows, swing_highs


def _cluster_zones(levels: list[dict], tolerance_pct: float = 0.025) -> list[dict]:
    """
    Sloučí blízké swingy do zón (tolerance 2.5 % pro týdenní TF).

    zone_low  = nejnižší candle_low  v clusteru (nejhlubší bod)
    zone_high = candle_high svíčky která má nejnižší candle_low
                (= high ankrové svíčky nejsilnějšího swingu)

    Tím zone_low/zone_high vždy odpovídají jedné konkrétní denní svíčce.
    """
    if not levels:
        return []

    sorted_levels = sorted(levels, key=lambda x: x["price"])
    clusters = []
    current  = [sorted_levels[0]]

    for level in sorted_levels[1:]:
        ref_price = current[0]["price"]
        if abs(level["price"] - ref_price) / ref_price <= tolerance_pct:
            current.append(level)
        else:
            clusters.append(current)
            current = [level]
    clusters.append(current)

    result = []
    for cluster in clusters:
        max_vol  = max(c["volume"] for c in cluster) or 1
        weights  = [c["strength"] + 0.3 * (c["volume"] / max_vol) for c in cluster]
        total_w  = sum(weights) or 1

        avg_strength = sum(c["strength"] for c in cluster) / len(cluster)
        total_volume = sum(c["volume"] for c in cluster)
        touch_count  = len(cluster)

        # Ankrová svíčka = ta s nejnižším candle_low v celém clusteru
        anchor   = min(cluster, key=lambda c: c["candle_low"])
        zone_lo  = round(anchor["candle_low"],  4)
        zone_hi  = round(anchor["candle_high"], 4)
        zone_mid = round((zone_lo + zone_hi) / 2, 4)

        result.append({
            "zone_low":    zone_lo,
            "zone_high":   zone_hi,
            "zone_mid":    zone_mid,
            "strength":    round(avg_strength, 4),
            "volume":      total_volume,
            "touch_count": touch_count,
            "dates":       [c["date"] for c in cluster],
        })

    return sorted(result, key=lambda x: x["zone_mid"])


# =========================================================
# DEMAND / SUPPLY ZONES (týdenní)
# =========================================================

def compute_zones(
    weekly_candles: list[dict],
    daily_candles:  list[dict],
    current_price:  float,
    lookback: int       = 3,
    min_strength: float = 0.02,
    n_zones: int        = 3,
) -> dict:
    """
    Demand/supply zóny z týdenních svíček zpřesněné denními daty.
    zone_low/zone_high = rozsah ankrové denní svíčky (té s extrémním low/high).
    """
    swing_lows, swing_highs = _find_swings(weekly_candles, daily_candles, lookback)

    strong_lows  = [s for s in swing_lows  if s["strength"] >= min_strength]
    strong_highs = [s for s in swing_highs if s["strength"] >= min_strength]

    demand_zones = _cluster_zones(strong_lows)
    supply_zones = _cluster_zones(strong_highs)

    demand = [z for z in demand_zones if z["zone_mid"] < current_price]
    supply = [z for z in supply_zones if z["zone_mid"] > current_price]

    demand_sorted = sorted(demand, key=lambda x: x["zone_mid"], reverse=True)[:n_zones]
    supply_sorted = sorted(supply, key=lambda x: x["zone_mid"])[:n_zones]

    return {
        "demand":    demand_sorted,
        "supply":    supply_sorted,
        "timeframe": "weekly",
    }


# =========================================================
# HLAVNÍ ENTRY POINT
# =========================================================

def compute_technical(raw_ohlcv: list[dict], current_price: float) -> dict:
    """
    Vstup: raw TwelveData denní OHLCV (nejnovější první), aktuální cena.

    RSI + MA — počítají se z denních svíček.
    Demand/Supply zóny — počítají se z týdenních svíček
                         (resampleovaných z denních dat).
    """
    candles = _parse_ohlcv(raw_ohlcv)   # chronologicky vzestupně

    if len(candles) < 20:
        return {"error": "Nedostatek dat", "candle_count": len(candles)}

    # ── Denní indikátory ─────────────────────────────────
    rsi     = compute_rsi(candles, period=14)
    sma_50  = compute_sma(candles, 50)
    sma_200 = compute_sma(candles, 200)
    ema_20  = compute_ema(candles, 20)

    above_ema20  = current_price > ema_20  if ema_20  else None
    above_sma50  = current_price > sma_50  if sma_50  else None
    above_sma200 = current_price > sma_200 if sma_200 else None

    bullish = sum(1 for x in [above_ema20, above_sma50, above_sma200] if x is True)
    bearish = sum(1 for x in [above_ema20, above_sma50, above_sma200] if x is False)
    trend   = "bullish" if bullish >= 2 else "bearish" if bearish >= 2 else "neutral"

    # ── Týdenní zóny zpřesněné denními svíčkami ──────────
    weekly = _resample_weekly(candles)
    if len(weekly) >= 10:
        zones = compute_zones(weekly, candles, current_price)
    else:
        zones = {"demand": [], "supply": [], "timeframe": "weekly"}

    result = {
        "rsi":           rsi,
        "sma_50":        sma_50,
        "sma_200":       sma_200,
        "ema_20":        ema_20,
        "trend":         trend,
        "above_ema20":   above_ema20,
        "above_sma50":   above_sma50,
        "above_sma200":  above_sma200,
        "zones":         zones,
        "candle_count":  len(candles),
        "weekly_count":  len(weekly),
    }

    if rsi is not None:
        result["rsi_signal"] = (
            "oversold"   if rsi < 30 else
            "overbought" if rsi > 70 else
            "neutral"
        )

    return result
