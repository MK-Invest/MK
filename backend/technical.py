"""
technical.py — Technická analýza z OHLCV dat
=============================================
Vstup:  seznam OHLCV záznamů z TwelveData (nejnovější první)
Výstup: RSI, klouzavé průměry, demand/supply zóny

Formát TwelveData záznamu:
  {"datetime": "2025-05-28", "open": "...", "high": "...",
   "low": "...", "close": "...", "volume": "..."}
"""

from __future__ import annotations
import math
from typing import Optional


# =========================================================
# UTIL
# =========================================================

def _f(x) -> Optional[float]:
    """Bezpečný float převod."""
    try:
        v = float(x)
        return None if (math.isnan(v) or math.isinf(v)) else v
    except Exception:
        return None


def _parse_ohlcv(raw: list[dict]) -> list[dict]:
    """
    Převede raw TwelveData záznamy na čisté floaty.
    Vstup je nejnovější první → obrátíme na chronologické pořadí
    pro výpočty (nejstarší první).
    """
    parsed = []
    for r in reversed(raw):   # chronologicky: nejstarší první
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
# RSI
# =========================================================

def compute_rsi(candles: list[dict], period: int = 14) -> Optional[float]:
    """
    Wilderův RSI (stejný jako TradingView, Yahoo Finance).

    Fáze 1: první průměrný gain/loss = prostý průměr prvních `period` změn
    Fáze 2: exponenciální vyhlazení (Wilder) pro zbytek série

    Vrátí RSI posledního dne (0–100).
    """
    closes = [c["close"] for c in candles]
    if len(closes) < period + 1:
        return None

    changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]

    # Fáze 1: seed průměry
    gains = [max(c, 0) for c in changes[:period]]
    losses = [abs(min(c, 0)) for c in changes[:period]]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    # Fáze 2: Wilderovo vyhlazení
    for change in changes[period:]:
        gain  = max(change, 0)
        loss  = abs(min(change, 0))
        avg_gain = (avg_gain * (period - 1) + gain)  / period
        avg_loss = (avg_loss * (period - 1) + loss) / period

    if avg_loss == 0:
        return 100.0

    rs  = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return round(rsi, 2)


# =========================================================
# MOVING AVERAGES
# =========================================================

def compute_sma(candles: list[dict], period: int) -> Optional[float]:
    """Simple Moving Average posledních `period` svíček."""
    closes = [c["close"] for c in candles]
    if len(closes) < period:
        return None
    return round(sum(closes[-period:]) / period, 4)


def compute_ema(candles: list[dict], period: int) -> Optional[float]:
    """
    Exponential Moving Average — stejný výpočet jako TradingView.
    Seed = SMA prvních `period` svíček.
    """
    closes = [c["close"] for c in candles]
    if len(closes) < period:
        return None

    k    = 2 / (period + 1)
    ema  = sum(closes[:period]) / period   # seed = SMA

    for price in closes[period:]:
        ema = price * k + ema * (1 - k)

    return round(ema, 4)


# =========================================================
# SWING DETECTION
# =========================================================

def _find_swings(candles: list[dict], lookback: int = 5) -> tuple[list, list]:
    """
    Identifikuje swing highs a swing lows.

    Swing high: svíčka jejíž `high` je nejvyšší v okně ±lookback svíček
    Swing low:  svíčka jejíž `low`  je nejnižší v okně ±lookback svíček

    Vrátí (swing_lows, swing_highs) — každý item:
      {"idx": int, "date": str, "price": float, "strength": float, "volume": float}
    """
    n = len(candles)
    swing_lows  = []
    swing_highs = []

    for i in range(lookback, n - lookback):
        window_highs = [candles[j]["high"] for j in range(i - lookback, i + lookback + 1) if j != i]
        window_lows  = [candles[j]["low"]  for j in range(i - lookback, i + lookback + 1) if j != i]

        c = candles[i]

        # Swing low
        if c["low"] < min(window_lows):
            # Síla = jak daleko cena od tohoto swingu odskočila
            # Měříme maximální vzdálenost close cen v následujících lookback svíčkách
            future_closes = [candles[j]["close"] for j in range(i + 1, min(i + lookback + 1, n))]
            if future_closes:
                max_move = max(future_closes) - c["low"]
                strength = max_move / c["low"]   # relativní pohyb
            else:
                strength = 0.0

            swing_lows.append({
                "idx":      i,
                "date":     c["date"],
                "price":    c["low"],
                "strength": round(strength, 4),
                "volume":   c["volume"],
            })

        # Swing high
        if c["high"] > max(window_highs):
            future_closes = [candles[j]["close"] for j in range(i + 1, min(i + lookback + 1, n))]
            if future_closes:
                max_move = c["high"] - min(future_closes)
                strength = max_move / c["high"]
            else:
                strength = 0.0

            swing_highs.append({
                "idx":      i,
                "date":     c["date"],
                "price":    c["high"],
                "strength": round(strength, 4),
                "volume":   c["volume"],
            })

    return swing_lows, swing_highs


def _cluster_levels(levels: list[dict], tolerance_pct: float = 0.015) -> list[dict]:
    """
    Sloučí blízké swingové úrovně do zón (tolerance = 1.5 % ceny).
    Výsledná zóna má cenu = váženou průměr (váha = strength × volume).

    Vrátí seznam zón seřazených podle ceny vzestupně.
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
        # Váha = strength + normalizovaný volume bonus
        max_vol = max(c["volume"] for c in cluster) or 1
        weights = [
            c["strength"] + 0.3 * (c["volume"] / max_vol)
            for c in cluster
        ]
        total_w = sum(weights) or 1
        avg_price = sum(c["price"] * w for c, w in zip(cluster, weights)) / total_w
        avg_strength = sum(c["strength"] for c in cluster) / len(cluster)
        total_volume = sum(c["volume"] for c in cluster)
        touch_count  = len(cluster)

        result.append({
            "price":       round(avg_price, 4),
            "strength":    round(avg_strength, 4),
            "volume":      total_volume,
            "touch_count": touch_count,
            "dates":       [c["date"] for c in cluster],
        })

    return sorted(result, key=lambda x: x["price"])


# =========================================================
# DEMAND / SUPPLY ZONES
# =========================================================

def compute_zones(
    candles: list[dict],
    current_price: float,
    lookback: int     = 5,
    min_strength: float = 0.015,   # min. 1.5 % pohyb od swingu
    n_zones: int      = 3,         # počet nejbližších zón na každé straně
) -> dict:
    """
    Identifikuje demand (support) a supply (resistance) zóny.

    Algoritmus:
    1. Najdi swing lows/highs s lookback oknem
    2. Odfiltruj slabé swingy (strength < min_strength)
    3. Seskup blízké úrovně do zón (±1.5 %)
    4. Vrať n_zones nejbližších pod a nad aktuální cenou

    Výstup:
      demand: [{price, strength, volume, touch_count, dates}, ...]  ← pod cenou
      supply: [{price, strength, volume, touch_count, dates}, ...]  ← nad cenou
    """
    swing_lows, swing_highs = _find_swings(candles, lookback)

    # Filtruj podle síly
    strong_lows  = [s for s in swing_lows  if s["strength"] >= min_strength]
    strong_highs = [s for s in swing_highs if s["strength"] >= min_strength]

    # Seskup do zón
    demand_zones = _cluster_levels(strong_lows)
    supply_zones = _cluster_levels(strong_highs)

    # Rozděl na pod/nad cenou
    demand = [z for z in demand_zones if z["price"] < current_price]
    supply = [z for z in supply_zones if z["price"] > current_price]

    # Nejbližší zóny (demand sestupně = nejblíže ceně první, supply vzestupně)
    demand_sorted = sorted(demand, key=lambda x: x["price"], reverse=True)[:n_zones]
    supply_sorted = sorted(supply, key=lambda x: x["price"])[:n_zones]

    return {
        "demand": demand_sorted,
        "supply": supply_sorted,
    }


# =========================================================
# HLAVNÍ ENTRY POINT
# =========================================================

def compute_technical(raw_ohlcv: list[dict], current_price: float) -> dict:
    """
    Spustí kompletní technickou analýzu z raw TwelveData OHLCV dat.

    Vstup:
      raw_ohlcv     — seznam diktů z TwelveData (nejnovější první)
      current_price — aktuální cena (z posledního close nebo quote)

    Výstup:
      {
        rsi:          float,           # 14-denní RSI
        sma_50:       float,
        sma_200:      float,
        ema_20:       float,
        trend:        "bullish"|"bearish"|"neutral",
        zones:        {demand: [...], supply: [...]},
        candle_count: int,
      }
    """
    candles = _parse_ohlcv(raw_ohlcv)

    if len(candles) < 20:
        return {"error": "Nedostatek dat pro technickou analýzu", "candle_count": len(candles)}

    rsi     = compute_rsi(candles, period=14)
    sma_50  = compute_sma(candles, 50)
    sma_200 = compute_sma(candles, 200)
    ema_20  = compute_ema(candles, 20)

    # Trend určení: cena vs. klouzavé průměry
    above_ema20  = current_price > ema_20  if ema_20  else None
    above_sma50  = current_price > sma_50  if sma_50  else None
    above_sma200 = current_price > sma_200 if sma_200 else None

    bullish_signals = sum(1 for x in [above_ema20, above_sma50, above_sma200] if x is True)
    bearish_signals = sum(1 for x in [above_ema20, above_sma50, above_sma200] if x is False)

    if bullish_signals >= 2:
        trend = "bullish"
    elif bearish_signals >= 2:
        trend = "bearish"
    else:
        trend = "neutral"

    zones = compute_zones(candles, current_price)

    result = {
        "rsi":          rsi,
        "sma_50":       sma_50,
        "sma_200":      sma_200,
        "ema_20":       ema_20,
        "trend":        trend,
        "above_ema20":  above_ema20,
        "above_sma50":  above_sma50,
        "above_sma200": above_sma200,
        "zones":        zones,
        "candle_count": len(candles),
    }

    # RSI signály
    if rsi is not None:
        result["rsi_signal"] = (
            "oversold"   if rsi < 30 else
            "overbought" if rsi > 70 else
            "neutral"
        )

    return result
