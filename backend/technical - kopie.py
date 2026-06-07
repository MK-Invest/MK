"""
technical.py — Technická analýza z OHLCV dat
=============================================
RSI (D/W/M), MA, EMA
Demand/Supply zóny (W → D anchor model)
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


def _normalize_date(date_str: str) -> Optional[str]:
    if not date_str:
        return None
    try:
        if " " in date_str:
            date_str = date_str.split(" ")[0]
        if "T" in date_str:
            date_str = date_str.split("T")[0]
        return date_str
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

        dt = _normalize_date(r.get("datetime", ""))

        if None not in (o, h, l, c) and dt:
            parsed.append({
                "date": dt,
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": v or 0.0,
            })

    return parsed


def _week_key(date_str: str) -> Optional[str]:
    try:
        date_str = _normalize_date(date_str)
        if not date_str:
            return None

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
# WEEKLY RESAMPLE
# =========================================================

def _resample_weekly(candles: list[dict]) -> list[dict]:
    from collections import OrderedDict

    weeks: OrderedDict = OrderedDict()

    for c in candles:
        wk = _week_key(c["date"])
        if not wk:
            continue

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
# RESAMPLE TF
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
# ZONES CORE LOGIC (W → D ANCHOR)
# =========================================================

def _find_weekly_swing_lows(weekly, lookback=3, n=2):
    swings = []
    for i in range(lookback, len(weekly) - lookback):
        w = weekly[i]
        prev = weekly[i - 1]

        window = [weekly[j]["low"] for j in range(i - lookback, i + lookback + 1) if j != i]

        if w["low"] < min(window) and prev["low"] >= w["low"]:
            future = weekly[i + 1:i + lookback + 1]
            if future and max(f["high"] for f in future) > w["high"]:
                swings.append(w)

    return list(reversed(swings))[:n]


def _find_weekly_swing_highs(weekly, lookback=3, n=2):
    swings = []
    for i in range(lookback, len(weekly) - lookback):
        w = weekly[i]
        prev = weekly[i - 1]

        window = [weekly[j]["high"] for j in range(i - lookback, i + lookback + 1) if j != i]

        if w["high"] > max(window) and prev["high"] <= w["high"]:
            future = weekly[i + 1:i + lookback + 1]
            if future and min(f["low"] for f in future) < w["low"]:
                swings.append(w)

    return list(reversed(swings))[:n]


def compute_zones(weekly, daily, current_price, lookback=3, n_zones=2):
    daily_by_week = defaultdict(list)

    for c in daily:
        wk = _week_key(c["date"])
        if wk:
            daily_by_week[wk].append(c)

    demand = []
    supply = []

    swing_lows = _find_weekly_swing_lows(weekly, lookback, n_zones)
    swing_highs = _find_weekly_swing_highs(weekly, lookback, n_zones)

    # -------------------------
    # DEMAND
    # -------------------------
    for sw in swing_lows:
        wk = sw.get("wk") or _week_key(sw["date"])
        if not wk:
            continue

        d = daily_by_week.get(wk, [])
        if not d:
            continue

        anchor = min(d, key=lambda x: x["low"])

        demand.append({
            "zone_low": anchor["low"],
            "zone_high": anchor["high"],
            "zone_mid": (anchor["low"] + anchor["high"]) / 2,
            "week_date": sw["date"],
            "anchor_date": anchor["date"],
        })

    demand = [z for z in demand if z["zone_mid"] < current_price]
    demand.sort(key=lambda z: z["zone_mid"], reverse=True)

    # -------------------------
    # SUPPLY
    # -------------------------
    for sw in swing_highs:
        wk = sw.get("wk") or _week_key(sw["date"])
        if not wk:
            continue

        d = daily_by_week.get(wk, [])
        if not d:
            continue

        anchor = max(d, key=lambda x: x["high"])

        supply.append({
            "zone_low": anchor["low"],
            "zone_high": anchor["high"],
            "zone_mid": (anchor["low"] + anchor["high"]) / 2,
            "week_date": sw["date"],
            "anchor_date": anchor["date"],
        })

    supply = [z for z in supply if z["zone_mid"] > current_price]
    supply.sort(key=lambda z: z["zone_mid"])

    return {
        "demand": demand,
        "supply": supply,
        "timeframe": "weekly",
    }


# =========================================================
# MAIN
# =========================================================

def compute_technical(raw_ohlcv: list[dict], current_price: float) -> dict:
    candles = _parse_ohlcv(raw_ohlcv)

    if len(candles) < 20:
        return {"error": "Nedostatek dat", "candle_count": len(candles)}

    rsi_d = compute_rsi(_resample_timeframe(candles, "D"), 14)
    rsi_w = compute_rsi(_resample_timeframe(candles, "W"), 14)
    rsi_m = compute_rsi(_resample_timeframe(candles, "M"), 14)

    weekly = _resample_weekly(candles)

    return {
        "rsi": {"D": rsi_d, "W": rsi_w, "M": rsi_m},
        "sma_50": compute_sma(candles, 50),
        "sma_200": compute_sma(candles, 200),
        "ema_20": compute_ema(candles, 20),
        "zones": compute_zones(weekly, candles, current_price),
        "candle_count": len(candles),
        "weekly_count": len(weekly),
    }
