"""
model.py — StockLens Valuation Engine
======================================
Dostupné modely (podle dat ze SEC pipeline):

  1. EV/EBITDA  — základní relativní ocenění (vždy dostupné)
  2. DCF        — diskontované FCF s terminální hodnotou (vyžaduje fcf)
  3. FCF Yield  — přímé ocenění přes cílový FCF yield (vyžaduje fcf)
  4. ROIC/EP    — Economic Profit model (vyžaduje roic + nopat)
  5. Composite  — vážený průměr všech dostupných modelů

Každý model vrací price target + confidence (0–1).
run_scenarios() vrací bear / base / bull přes všechny modely najednou.
"""

from __future__ import annotations
import math
from typing import Optional


# =========================================================
# SAFE MATH
# =========================================================

def _safe(x) -> Optional[float]:
    try:
        v = float(x)
        return None if (math.isnan(v) or math.isinf(v)) else v
    except Exception:
        return None


def _pct(label: str, v: Optional[float]) -> str:
    return f"{label}={v:.1%}" if v is not None else f"{label}=N/A"


# =========================================================
# MODEL 1 — EV / EBITDA  (relativní ocenění)
# =========================================================

def model_ev_ebitda(
    revenue: float,
    ebitda_margin: float,
    ev_ebitda_multiple: float,
    net_debt: float,
    shares: float,
    revenue_growth: float = 0.0,
    years: int = 1,
) -> dict:
    """
    Klasický EV/EBITDA model s volitelným forward revenue growth.

    price = (EBITDA_forward × multiple − net_debt) / shares
    """
    rev_forward = revenue * ((1 + revenue_growth) ** years)
    ebitda      = _safe(rev_forward * ebitda_margin)
    if ebitda is None:
        return {"model": "ev_ebitda", "price": None, "confidence": 0.0}

    ev     = ebitda * ev_ebitda_multiple
    equity = ev - net_debt
    price  = _safe(equity / shares) if shares else None

    return {
        "model":      "ev_ebitda",
        "price":      price,
        "ebitda":     ebitda,
        "ev":         ev,
        "equity":     equity,
        "confidence": 0.55,   # relativní model — střední spolehlivost
    }


# =========================================================
# MODEL 2 — DCF  (diskontované FCF)
# =========================================================

def model_dcf(
    fcf: float,
    net_debt: float,
    shares: float,
    wacc: float       = 0.10,
    fcf_growth: float = 0.07,
    terminal_growth: float = 0.025,
    years: int        = 5,
) -> dict:
    """
    Dvoustupňový DCF:
      Fáze 1: explicitní FCF projekce na `years` let
      Fáze 2: Gordonův model terminální hodnoty

    Omezení: fcf_growth max 35 %, terminal_growth < wacc (jinak model diverguje).
    """
    fcf_g  = min(abs(fcf_growth), 0.35) * (1 if fcf_growth >= 0 else -1)
    t_grow = min(terminal_growth, wacc - 0.005)   # terminální růst < WACC

    pv_fcfs = 0.0
    cf = fcf
    for t in range(1, years + 1):
        cf     *= (1 + fcf_g)
        pv_fcfs += cf / ((1 + wacc) ** t)

    # Terminální hodnota (Gordonův model)
    terminal_fcf = cf * (1 + t_grow)
    terminal_val = terminal_fcf / (wacc - t_grow)
    pv_terminal  = terminal_val / ((1 + wacc) ** years)

    intrinsic_ev  = pv_fcfs + pv_terminal
    equity_value  = intrinsic_ev - net_debt
    price         = _safe(equity_value / shares) if shares else None

    # Confidence: závisí na znaménku FCF a rozumnosti WACC
    base_conf = 0.75 if fcf > 0 else 0.35

    return {
        "model":        "dcf",
        "price":        price,
        "pv_fcfs":      pv_fcfs,
        "pv_terminal":  pv_terminal,
        "intrinsic_ev": intrinsic_ev,
        "equity_value": equity_value,
        "confidence":   base_conf,
    }


# =========================================================
# MODEL 3 — FCF YIELD  (přímé ocenění)
# =========================================================

def model_fcf_yield(
    fcf: float,
    net_debt: float,
    shares: float,
    target_yield: float = 0.04,   # 4 % FCF yield jako "fair value"
) -> dict:
    """
    Obrácený FCF yield:
      fair market cap = FCF / target_yield
      price = (fair_mc − net_debt) / shares

    target_yield 4 % odpovídá přibližně P/FCF ≈ 25× (pro průměrnou firmu S&P 500).
    """
    if target_yield <= 0:
        return {"model": "fcf_yield", "price": None, "confidence": 0.0}

    fair_mc      = fcf / target_yield
    equity_value = fair_mc - net_debt
    price        = _safe(equity_value / shares) if shares else None

    confidence   = 0.65 if fcf > 0 else 0.25

    return {
        "model":        "fcf_yield",
        "price":        price,
        "fair_mc":      fair_mc,
        "equity_value": equity_value,
        "target_yield": target_yield,
        "confidence":   confidence,
    }


# =========================================================
# MODEL 4 — ROIC / Economic Profit
# =========================================================

def model_roic_ep(
    nopat: float,
    roic: float,
    net_debt: float,
    shares: float,
    wacc: float       = 0.10,
    growth: float     = 0.05,
    years: int        = 5,
    fade_rate: float  = 0.15,   # jak rychle se ROIC "vrací k průměru"
) -> dict:
    """
    Economic Profit (EP) model:
      EP = NOPAT − (Invested Capital × WACC)
      = NOPAT × (1 − WACC/ROIC)          [za předpokladu IC = NOPAT/ROIC]

    ROIC fade: každý rok se ROIC přibližuje k WACC o fade_rate × (ROIC − WACC).
    Modely bez fade nadhodnocují firmy s dočasně vysokým ROIC.

    Confidence je vyšší pro firmy s ROIC > WACC (skutečná ekonomická přidaná hodnota).
    """
    if roic <= 0:
        return {"model": "roic_ep", "price": None, "confidence": 0.0}

    invested_capital = nopat / roic   # IC = NOPAT / ROIC

    pv_ep   = 0.0
    ic      = invested_capital
    cur_nopat = nopat
    cur_roic  = roic

    for t in range(1, years + 1):
        # Růst investovaného kapitálu
        ic        *= (1 + growth)
        cur_nopat  = ic * cur_roic

        # Economic Profit tohoto roku
        ep  = cur_nopat - ic * wacc
        pv_ep += ep / ((1 + wacc) ** t)

        # ROIC fade směrem k WACC
        cur_roic -= fade_rate * (cur_roic - wacc)
        cur_roic  = max(cur_roic, wacc)   # nepůjde pod WACC

    # Terminální EP (bez fade, ROIC stabilizovaný)
    terminal_ep  = (ic * cur_roic - ic * wacc)
    pv_terminal  = (terminal_ep / (wacc - 0.02)) / ((1 + wacc) ** years)

    intrinsic_equity = invested_capital + pv_ep + pv_terminal
    equity_value     = intrinsic_equity - net_debt
    price            = _safe(equity_value / shares) if shares else None

    confidence = 0.70 if roic > wacc else 0.40

    return {
        "model":             "roic_ep",
        "price":             price,
        "invested_capital":  invested_capital,
        "pv_economic_profit": pv_ep,
        "pv_terminal":       pv_terminal,
        "equity_value":      equity_value,
        "confidence":        confidence,
    }


# =========================================================
# COMPOSITE — vážený průměr dostupných modelů
# =========================================================

def composite_price(models: list[dict]) -> dict:
    """
    Vážený průměr price targetů všech modelů podle jejich confidence.
    Modely bez price nebo s confidence = 0 jsou ignorovány.
    """
    valid = [m for m in models if m.get("price") is not None and m.get("confidence", 0) > 0]
    if not valid:
        return {"price": None, "confidence": 0.0, "models_used": []}

    total_w  = sum(m["confidence"] for m in valid)
    w_price  = sum(m["price"] * m["confidence"] for m in valid) / total_w
    avg_conf = total_w / len(valid)   # průměrná confidence (normalizovaná)

    return {
        "price":       _safe(w_price),
        "confidence":  min(avg_conf, 1.0),
        "models_used": [m["model"] for m in valid],
        "weights":     {m["model"]: round(m["confidence"] / total_w, 3) for m in valid},
    }


# =========================================================
# SCÉNÁŘOVÉ PARAMETRY
# =========================================================

# Multiplikátory pro bear / base / bull scénáře
SCENARIO_PARAMS = {
    "bear": {
        "revenue_growth_adj":   -0.05,   # revenue o 5 % níž než base
        "ebitda_margin_adj":    -0.03,   # margin stlačen
        "ev_ebitda_adj":        -0.20,   # multiple komprese
        "fcf_growth":           -0.05,
        "wacc_adj":             +0.02,   # vyšší riziko
        "target_yield_adj":     +0.01,   # investoři chtějí vyšší yield
        "roic_growth_adj":      -0.02,
        "label":                "Bear",
    },
    "base": {
        "revenue_growth_adj":    0.0,
        "ebitda_margin_adj":     0.0,
        "ev_ebitda_adj":         0.0,
        "fcf_growth":            0.07,
        "wacc_adj":              0.0,
        "target_yield_adj":      0.0,
        "roic_growth_adj":       0.0,
        "label":                "Base",
    },
    "bull": {
        "revenue_growth_adj":   +0.05,
        "ebitda_margin_adj":    +0.03,
        "ev_ebitda_adj":        +0.20,
        "fcf_growth":           +0.15,
        "wacc_adj":             -0.01,   # nižší riziko / lepší podmínky
        "target_yield_adj":     -0.01,
        "roic_growth_adj":      +0.03,
        "label":                "Bull",
    },
}


# =========================================================
# RUN SCENARIOS  (hlavní entry point)
# =========================================================

def run_scenarios(input_data: dict, wacc: float = 0.10, years: int = 5) -> dict:
    """
    Spustí bear / base / bull přes všechny dostupné modely.

    Povinné vstupy:
      revenue, ebitda_margin, ev_ebitda_multiple, net_debt, shares

    Volitelné (odemykají další modely):
      fcf        → DCF + FCF Yield
      nopat      → ROIC/EP (spolu s roic)
      roic       → ROIC/EP
      tax_rate   → informativně
      revenue_growth → base forward growth pro EV/EBITDA

    Výstup pro každý scénář:
      {
        label, models: { ev_ebitda, dcf, fcf_yield, roic_ep },
        composite: { price, confidence, models_used, weights }
      }
    """

    # ── Základní vstupy ──────────────────────────────────
    revenue            = float(input_data.get("revenue") or 0)
    ebitda_margin      = float(input_data.get("ebitda_margin") or 0.20)
    ev_ebitda_multiple = float(input_data.get("ev_ebitda_multiple") or 15.0)
    net_debt           = float(input_data.get("net_debt") or 0)
    shares             = float(input_data.get("shares") or 1)
    revenue_growth     = float(input_data.get("revenue_growth") or 0.05)

    # ── Pokročilé vstupy (optional) ──────────────────────
    fcf      = _safe(input_data.get("fcf"))
    nopat    = _safe(input_data.get("nopat"))
    roic     = _safe(input_data.get("roic"))

    result = {}

    for scenario, sp in SCENARIO_PARAMS.items():
        models_out = {}

        # ── Model 1: EV/EBITDA ───────────────────────────
        adj_growth   = revenue_growth + sp["revenue_growth_adj"]
        adj_margin   = max(ebitda_margin + sp["ebitda_margin_adj"], 0.01)
        adj_multiple = max(ev_ebitda_multiple * (1 + sp["ev_ebitda_adj"]), 1.0)

        models_out["ev_ebitda"] = model_ev_ebitda(
            revenue            = revenue,
            ebitda_margin      = adj_margin,
            ev_ebitda_multiple = adj_multiple,
            net_debt           = net_debt,
            shares             = shares,
            revenue_growth     = adj_growth,
            years              = years,
        )

        # ── Model 2: DCF ─────────────────────────────────
        if fcf is not None:
            adj_wacc = max(wacc + sp["wacc_adj"], 0.04)
            models_out["dcf"] = model_dcf(
                fcf            = fcf,
                net_debt       = net_debt,
                shares         = shares,
                wacc           = adj_wacc,
                fcf_growth     = sp["fcf_growth"],
                terminal_growth= 0.025,
                years          = years,
            )

        # ── Model 3: FCF Yield ────────────────────────────
        if fcf is not None:
            base_yield = 0.04
            adj_yield  = max(base_yield + sp["target_yield_adj"], 0.01)
            models_out["fcf_yield"] = model_fcf_yield(
                fcf          = fcf,
                net_debt     = net_debt,
                shares       = shares,
                target_yield = adj_yield,
            )

        # ── Model 4: ROIC / EP ────────────────────────────
        if nopat is not None and roic is not None and roic > 0:
            adj_roic_growth = revenue_growth + sp["roic_growth_adj"]
            adj_wacc        = max(wacc + sp["wacc_adj"], 0.04)
            models_out["roic_ep"] = model_roic_ep(
                nopat    = nopat,
                roic     = roic,
                net_debt = net_debt,
                shares   = shares,
                wacc     = adj_wacc,
                growth   = max(adj_roic_growth, 0.0),
                years    = years,
            )

        # ── Composite ─────────────────────────────────────
        comp = composite_price(list(models_out.values()))

        result[scenario] = {
            "label":     sp["label"],
            "models":    models_out,
            "composite": comp,
            # Zpětná kompatibilita — "price" na top level
            "price":     comp["price"],
            "ebitda":    models_out["ev_ebitda"].get("ebitda"),
            "ev":        models_out["ev_ebitda"].get("ev"),
            "equity":    models_out["ev_ebitda"].get("equity"),
        }

    return result
