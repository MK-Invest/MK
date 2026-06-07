"""
technical.py — Technická analýza z OHLCV dat
=============================================
RSI (D/W/M), MA, EMA
Demand/Supply zóny
"""

from __future__ import annotations
import math
from typing import Optional
from collections import defaultdict
from datetime import date as _date, datetime


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
    parsed = []
    for r in reversed(raw):
        o = _f(r.get("open"))
        h = _f(r.get("high"))
        l = _f(r.get("low"))
        c = _f(r.get("close"))
        v = _f(r.get("volume"))

        if None not in (o, h, l, c):
            dt = r.get("datetime", "")

            # 🔥 FIX: sjednocení formátu data
            if " " in dt:
                dt = dt.split(" ")[0]

            parsed.append({
                "date": dt,
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": v or 0.0,
            })

    return parsed

def _week_key(date_str: str) -> str:
    try:
        # normalize datetime string
        if not date_str:
            return None

        if " " in date_str:
            date_str = date_str.split(" ")[0]
        if "T" in date_str:
            date_str = date_str.split("T")[0]

        d = _date.fromisoformat(date_str)
        iso = d.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"

    except Exception:
        return None

def _is_bearish(c: dict) -> bool:
    return c["close"] < c["open"]


def _is_bullish(c: dict) -> bool:
    return c["close"] > c["open"]


# =========================================================
# RESAMPLE WEEKLY
# =========================================================

def _resample_weekly(candles: list[dict]) -> list[dict]:
    from collections import OrderedDict

    weeks: OrderedDict = OrderedDict()

    for c in candles:
        wk = _week_key(c["date"])

        if wk not in weeks:
            weeks[wk] = {
                "date": c["date"],
                "open": c["open"],
                "high": c["high"],
                "low": c["low"],
                "close": c["close"],
                "volume": c["volume"],
                "wk": wk,
            }
        else:
            w = weeks[wk]
            w["high"] = max(w["high"], c["high"])
            w["low"] = min(w["low"], c["low"])
            w["close"] = c["close"]
            w["volume"] += c["volume"]
            w["date"] = c["date"]

    return list(weeks.values())


# =========================================================
# RSI
# =========================================================

def compute_rsi(candles: list[dict], period: int = 14) -> Optional[float]:
    closes = [c["close"] for c in candles]
    if len(closes) < period + 1:
        return None

    changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]

    avg_gain = sum(max(c, 0) for c in changes[:period]) / period
    avg_loss = sum(abs(min(c, 0)) for c in changes[:period]) / period

    for change in changes[period:]:
        avg_gain = (avg_gain * (period - 1) + max(change, 0)) / period
        avg_loss = (avg_loss * (period - 1) + abs(min(change, 0))) / period

    if avg_loss == 0:
        return 100.0

    return round(100 - (100 / (1 + avg_gain / avg_loss)), 2)


# =========================================================
# TIMEFRAME RESAMPLE (RSI)
# =========================================================

def _resample_timeframe(candles: list[dict], mode: str):
    if mode == "D":
        return candles

    grouped = defaultdict(list)

    for c in candles:
        dt = datetime.fromisoformat(c["date"])

        if mode == "W":
            key = f"{dt.isocalendar().year}-W{dt.isocalendar().week:02d}"
        elif mode == "M":
            key = f"{dt.year}-{dt.month:02d}"
        else:
            key = "D"

        grouped[key].append(c)

    out = []

    for k in sorted(grouped.keys()):
        group = sorted(grouped[k], key=lambda x: x["date"])

        out.append({
            "date": group[-1]["date"],
            "open": group[0]["open"],
            "high": max(x["high"] for x in group),
            "low": min(x["low"] for x in group),
            "close": group[-1]["close"],
            "volume": sum(x["volume"] for x in group),
        })

    return out


# =========================================================
# MA
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

    k = 2 / (period + 1)
    ema = sum(closes[:period]) / period

    for price in closes[period:]:
        ema = price * k + ema * (1 - k)

    return round(ema, 4)


# =========================================================
# DEMAND / SUPPLY ZÓNY — nová logika
# =========================================================

def _find_weekly_swing_lows(weekly: list[dict], lookback: int = 3, n: int = 2) -> list[dict]:
    """
    Najde posledních n swing lows na týdenních svíčkách.
    Swing low = týdenní svíčka jejíž low je nejnižší v okně ±lookback
                a předchozí týden nemá nižší low.
    Vrátí seřazené od nejnovějšího.
    """
    swings = []
    wn = len(weekly)

    for i in range(lookback, wn - lookback):
        w    = weekly[i]
        prev = weekly[i - 1]

        window_lows = [weekly[j]["low"] for j in range(i - lookback, i + lookback + 1) if j != i]

        if w["low"] < min(window_lows) and prev["low"] >= w["low"]:
            # Ověř že po tomto swingu přišel pohyb nahoru (impulz)
            future = weekly[i + 1: i + lookback + 1]
            if future and max(f["high"] for f in future) > w["high"]:
                swings.append(w)

    # Vrať posledních n (nejnovější první)
    return list(reversed(swings))[:n]


def _find_weekly_swing_highs(weekly: list[dict], lookback: int = 3, n: int = 2) -> list[dict]:
    """Posledních n swing highs — symetricky k swing lows."""
    swings = []
    wn = len(weekly)

    for i in range(lookback, wn - lookback):
        w    = weekly[i]
        prev = weekly[i - 1]

        window_highs = [weekly[j]["high"] for j in range(i - lookback, i + lookback + 1) if j != i]

        if w["high"] > max(window_highs) and prev["high"] <= w["high"]:
            future = weekly[i + 1: i + lookback + 1]
            if future and min(f["low"] for f in future) < w["low"]:
                swings.append(w)

    return list(reversed(swings))[:n]


def _find_last_bearish_before_impulse(day_candles: list[dict]) -> Optional[dict]:
    """
    Z denních svíček swing low týdne najdi:
    1. První silný bullish den (= impulzní svíčka — body > 1 % a close > open)
    2. Poslední bearish svíčku PŘED tím bullish dnem

    Vrátí tu poslední bearish svíčku, nebo první svíčku týdne jako fallback.
    """
    if not day_candles:
        return None

    # Najdi první silný bullish den
    impulse_idx = None
    for i, c in enumerate(day_candles):
        body_pct = (c["close"] - c["open"]) / c["open"] if c["open"] else 0
        if _is_bullish(c) and body_pct > 0.005:   # tělo > 0.5 %
            impulse_idx = i
            break

    if impulse_idx is None:
        # Žádný silný bullish den → vezmi první svíčku jako fallback
        return day_candles[0]

    if impulse_idx == 0:
        # Impulz je hned první den → vezmi ji jako zónu
        return day_candles[0]

    # Hledej poslední bearish svíčku před impulzem
    for i in range(impulse_idx - 1, -1, -1):
        if _is_bearish(day_candles[i]):
            return day_candles[i]

    # Všechny dny před impulzem jsou bullish → vezmi den těsně před impulzem
    return day_candles[impulse_idx - 1]


def _find_last_bullish_before_impulse(day_candles: list[dict]) -> Optional[dict]:
    """Symetrie pro supply zóny — poslední bullish svíčka před bearish impulzem."""
    if not day_candles:
        return None

    impulse_idx = None
    for i, c in enumerate(day_candles):
        body_pct = (c["open"] - c["close"]) / c["open"] if c["open"] else 0
        if _is_bearish(c) and body_pct > 0.005:
            impulse_idx = i
            break

    if impulse_idx is None:
        return day_candles[0]
    if impulse_idx == 0:
        return day_candles[0]

    for i in range(impulse_idx - 1, -1, -1):
        if _is_bullish(day_candles[i]):
            return day_candles[i]

    return day_candles[impulse_idx - 1]


def compute_zones(
    weekly:        list[dict],
    daily:         list[dict],
    current_price: float,
    lookback:      int = 3,
    n_zones:       int = 2,
) -> dict:
    """
    Demand zóny:
      1. Najdi posledních n_zones swing lows na týdenním TF
      2. Pro každý swing low týden seskup denní svíčky
      3. Najdi poslední bearish denní svíčku před prvním silným bullish dnem
      4. zone_low = low té svíčky, zone_high = high té svíčky

    Supply zóny — symetricky.
    """
    # Seskup denní svíčky podle týdne
    daily_by_week: dict = defaultdict(list)
    for c in daily:
        daily_by_week[_week_key(c["date"])].append(c)

    # ── Demand zóny ──────────────────────────────────────
    swing_lows = _find_weekly_swing_lows(weekly, lookback, n_zones)
    demand = []

    for sw in swing_lows:
        wk = sw.get("wk") or _week_key(sw["date"])
        day_candles = sorted(daily_by_week.get(wk, []), key=lambda c: c["date"])

        if not day_candles:
            # Fallback na raw weekly svíčku
            anchor = sw
        else:
            anchor = _find_last_bearish_before_impulse(day_candles)
            if anchor is None:
                anchor = day_candles[0]

        zone_low  = round(anchor["low"],  4)
        zone_high = round(anchor["high"], 4)

        demand.append({
            "zone_low":   zone_low,
            "zone_high":  zone_high,
            "zone_mid":   round((zone_low + zone_high) / 2, 4),
            "week_date":  sw["date"],
            "anchor_date": anchor["date"],
        })

    # Filtruj zóny pod aktuální cenou, nejbližší první
    demand = [z for z in demand if z["zone_mid"] < current_price]
    demand.sort(key=lambda z: z["zone_mid"], reverse=True)

    # ── Supply zóny ──────────────────────────────────────
    swing_highs = _find_weekly_swing_highs(weekly, lookback, n_zones)
    supply = []

    for sw in swing_highs:
        wk = sw.get("wk") or _week_key(sw["date"])
        day_candles = sorted(daily_by_week.get(wk, []), key=lambda c: c["date"])

        if not day_candles:
            anchor = sw
        else:
            anchor = _find_last_bullish_before_impulse(day_candles)
            if anchor is None:
                anchor = day_candles[-1]

        zone_low  = round(anchor["low"],  4)
        zone_high = round(anchor["high"], 4)

        supply.append({
            "zone_low":    zone_low,
            "zone_high":   zone_high,
            "zone_mid":    round((zone_low + zone_high) / 2, 4),
            "week_date":   sw["date"],
            "anchor_date": anchor["date"],
        })

    supply = [z for z in supply if z["zone_mid"] > current_price]
    supply.sort(key=lambda z: z["zone_mid"])

    return {
        "demand":    demand,
        "supply":    supply,
        "timeframe": "weekly",
    }

# =========================================================
# MAIN
# =========================================================

def compute_technical(raw_ohlcv: list[dict], current_price: float) -> dict:
    candles = _parse_ohlcv(raw_ohlcv)

    if len(candles) < 20:
        return {"error": "Nedostatek dat", "candle_count": len(candles)}

    # ── RSI MULTI TIMEFRAME ──
    rsi_d = compute_rsi(_resample_timeframe(candles, "D"), 14)
    rsi_w = compute_rsi(_resample_timeframe(candles, "W"), 14)
    rsi_m = compute_rsi(_resample_timeframe(candles, "M"), 14)

    rsi_obj = {
        "D": rsi_d,
        "W": rsi_w,
        "M": rsi_m,
    }

    # ── MA ──
    sma_50 = compute_sma(candles, 50)
    sma_200 = compute_sma(candles, 200)
    ema_20 = compute_ema(candles, 20)

    above_ema20 = current_price > ema_20 if ema_20 else None
    above_sma50 = current_price > sma_50 if sma_50 else None
    above_sma200 = current_price > sma_200 if sma_200 else None

    bullish = sum(x is True for x in [above_ema20, above_sma50, above_sma200])
    bearish = sum(x is False for x in [above_ema20, above_sma50, above_sma200])

    trend = "bullish" if bullish >= 2 else "bearish" if bearish >= 2 else "neutral"

    weekly = _resample_weekly(candles)

    result = {
        "rsi": rsi_obj,

        "sma_50": sma_50,
        "sma_200": sma_200,
        "ema_20": ema_20,

        "trend": trend,

        "above_ema20": above_ema20,
        "above_sma50": above_sma50,
        "above_sma200": above_sma200,

        "zones": {"demand": [], "supply": [], "timeframe": "weekly"},

        "candle_count": len(candles),
        "weekly_count": len(weekly),
    }

    if rsi_d is not None:
        result["rsi_signal"] = (
            "oversold" if rsi_d < 30 else
            "overbought" if rsi_d > 70 else
            "neutral"
        )

    return result
