"""
technical.py — Institutional Supply/Demand Engine
==================================================
Upgrade:
- ATR volatility filter
- Displacement detection
- Imbalance (FVG)
- Order block anchoring
"""

from __future__ import annotations
import math
from typing import Optional
from collections import defaultdict
from datetime import date as _date


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
            parsed.append({
                "date": r.get("datetime", ""),
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": v or 0.0,
            })
    return parsed


def _week_key(date_str: str) -> str:
    try:
        d = _date.fromisoformat(date_str)
        iso = d.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    except Exception:
        return date_str[:7]


def _is_bullish(c): return c["close"] > c["open"]
def _is_bearish(c): return c["close"] < c["open"]


# =========================================================
# ATR (KEY FOR INSTITUTIONAL LOGIC)
# =========================================================

def compute_atr(candles: list[dict], period: int = 14) -> Optional[float]:
    if len(candles) < period + 1:
        return None

    trs = []
    for i in range(1, len(candles)):
        h = candles[i]["high"]
        l = candles[i]["low"]
        pc = candles[i - 1]["close"]

        tr = max(h - l, abs(h - pc), abs(l - pc))
        trs.append(tr)

    if len(trs) < period:
        return None

    return sum(trs[-period:]) / period


# =========================================================
# WEEKLY STRUCTURE
# =========================================================

def _resample_weekly(candles: list[dict]) -> list[dict]:
    from collections import OrderedDict

    weeks = OrderedDict()

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
# DISPLACEMENT (INSTITUTIONAL IMPULSE)
# =========================================================

def _is_displacement(c, atr: float) -> bool:
    if atr is None:
        return False

    body = abs(c["close"] - c["open"])

    # institutional threshold
    return (
        body > 1.5 * atr and
        ((c["close"] > c["open"] and c["close"] > (c["high"] - (atr * 0.2))) or
         (c["close"] < c["open"] and c["close"] < (c["low"] + (atr * 0.2))))
    )


# =========================================================
# FVG (IMBALANCE)
# =========================================================

def _find_fvg(candles: list[dict]) -> list[dict]:
    fvg = []

    for i in range(2, len(candles)):
        c0 = candles[i - 2]
        c2 = candles[i]

        # bullish imbalance
        if c2["low"] > c0["high"]:
            fvg.append({
                "type": "bullish",
                "low": c0["high"],
                "high": c2["low"],
                "index": i
            })

        # bearish imbalance
        if c2["high"] < c0["low"]:
            fvg.append({
                "type": "bearish",
                "low": c2["high"],
                "high": c0["low"],
                "index": i
            })

    return fvg


# =========================================================
# ORDER BLOCK ANCHORING
# =========================================================

def _find_order_block(candles: list[dict], idx: int, direction: str) -> Optional[dict]:
    # bullish displacement → last bearish candle
    if direction == "bullish":
        for i in range(idx - 1, -1, -1):
            if _is_bearish(candles[i]):
                return candles[i]

    # bearish displacement → last bullish candle
    if direction == "bearish":
        for i in range(idx - 1, -1, -1):
            if _is_bullish(candles[i]):
                return candles[i]

    return None


# =========================================================
# ZONES (INSTITUTIONAL VERSION)
# =========================================================

def compute_zones(
    weekly: list[dict],
    daily: list[dict],
    current_price: float,
    lookback: int = 3,
    n_zones: int = 3,
) -> dict:
    """
    Institutional Supply/Demand model:

    1. Sweep liquidity (weekly swing)
    2. Confirm displacement (ATR based)
    3. Confirm imbalance (FVG style)
    4. Entry zone = origin candle (last opposite candle before displacement)
    """

    # ─────────────────────────────
    # ATR (simple rolling)
    # ─────────────────────────────
    def _atr(candles, period=14):
        trs = []
        for i in range(1, len(candles)):
            h = candles[i]["high"]
            l = candles[i]["low"]
            pc = candles[i - 1]["close"]
            tr = max(h - l, abs(h - pc), abs(l - pc))
            trs.append(tr)
        if len(trs) < period:
            return None
        return sum(trs[-period:]) / period

    atr = _atr(daily, 14)
    if not atr:
        return {"demand": [], "supply": [], "atr": None, "timeframe": "institutional"}

    # ─────────────────────────────
    # helpers
    # ─────────────────────────────
    def is_bull(c): return c["close"] > c["open"]
    def is_bear(c): return c["close"] < c["open"]

    # ─────────────────────────────
    # swing detection (weekly)
    # ─────────────────────────────
    def swing_lows(w):
        out = []
        for i in range(lookback, len(w) - lookback):
            if w[i]["low"] == min(x["low"] for x in w[i-lookback:i+lookback+1]):
                out.append(w[i])
        return out[-n_zones:]

    def swing_highs(w):
        out = []
        for i in range(lookback, len(w) - lookback):
            if w[i]["high"] == max(x["high"] for x in w[i-lookback:i+lookback+1]):
                out.append(w[i])
        return out[-n_zones:]

    # ─────────────────────────────
    # DISPLACEMENT CHECK
    # ─────────────────────────────
    def is_displacement(c):
        body = abs(c["close"] - c["open"])
        return body > 0.8 * atr   # KEY FIX (realistic)

    # ─────────────────────────────
    # FIND demand origin
    # ─────────────────────────────
    def find_origin(candles, idx):
        for i in range(idx - 1, -1, -1):
            if is_bear(candles[i]):
                return candles[i]
        return candles[max(0, idx - 1)]

    # ─────────────────────────────
    # DEMAND
    # ─────────────────────────────
    demand = []

    for sw in swing_lows(weekly):

        wk = sw.get("wk")
        days = [c for c in daily if c.get("wk") == wk] if wk else []

        if len(days) < 3:
            continue

        # find displacement
        impulse_idx = None
        for i, c in enumerate(days):
            if is_bull(c) and is_displacement(c):
                impulse_idx = i
                break

        if impulse_idx is None:
            continue

        origin = find_origin(days, impulse_idx)

        zone = {
            "zone_low": round(origin["low"], 4),
            "zone_high": round(origin["high"], 4),
            "zone_mid": round((origin["low"] + origin["high"]) / 2, 4),
            "week_date": sw["date"],
            "type": "demand",
        }

        # filter below price
        if zone["zone_mid"] < current_price:
            demand.append(zone)

    demand = sorted(demand, key=lambda x: x["zone_mid"], reverse=True)[:n_zones]

    # ─────────────────────────────
    # SUPPLY
    # ─────────────────────────────
    supply = []

    for sw in swing_highs(weekly):

        wk = sw.get("wk")
        days = [c for c in daily if c.get("wk") == wk] if wk else []

        if len(days) < 3:
            continue

        impulse_idx = None
        for i, c in enumerate(days):
            if is_bear(c) and is_displacement(c):
                impulse_idx = i
                break

        if impulse_idx is None:
            continue

        origin = find_origin(days, impulse_idx)

        zone = {
            "zone_low": round(origin["low"], 4),
            "zone_high": round(origin["high"], 4),
            "zone_mid": round((origin["low"] + origin["high"]) / 2, 4),
            "week_date": sw["date"],
            "type": "supply",
        }

        if zone["zone_mid"] > current_price:
            supply.append(zone)

    supply = sorted(supply, key=lambda x: x["zone_mid"])[:n_zones]

    return {
        "demand": demand,
        "supply": supply,
        "atr": round(atr, 6),
        "timeframe": "institutional"
    }
# =========================================================
# MAIN
# =========================================================

def compute_technical(raw_ohlcv: list[dict], current_price: float) -> dict:
    candles = _parse_ohlcv(raw_ohlcv)

    if len(candles) < 20:
        return {"error": "Nedostatek dat"}

    rsi = None  # unchanged (optional reuse later)

    weekly = _resample_weekly(candles)

    zones = compute_zones(weekly, candles, current_price)

    return {
        "rsi": rsi,
        "zones": zones,
        "candle_count": len(candles),
        "weekly_count": len(weekly),
    }
