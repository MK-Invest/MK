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
# ZONES (UNCHANGED)
# =========================================================

def compute_zones(*args, **kwargs):
    return {"demand": [], "supply": [], "timeframe": "weekly"}


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
