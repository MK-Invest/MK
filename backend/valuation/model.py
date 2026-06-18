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
        "confidence": 0.55,
    }


# =========================================================
# MODEL 2 — DCF  (diskontované FCF)
# =========================================================

def model_dcf(
    fcf: float,
    net_debt: float,
    shares: float,
    wacc: float             = 0.10,
    fcf_growth: float       = 0.06,
    terminal_growth: float  = 0.025,
    years: int              = 10,
) -> dict:
    """
    Dvoustupňový DCF:
      Fáze 1: explicitní FCF projekce na `years` let
      Fáze 2: Gordonův model terminální hodnoty

    fcf_growth je odvozený jako min(revenue_cagr_5y, net_income_cagr_5y, 0.15)
    v run_scenarios() před voláním tohoto modelu.

    Omezení: fcf_growth max 35 %, terminal_growth < wacc (jinak model diverguje).
    """
    fcf_g  = min(abs(fcf_growth), 0.35) * (1 if fcf_growth >= 0 else -1)
    t_grow = min(terminal_growth, wacc - 0.005)

    pv_fcfs = 0.0
    cf = fcf
    for t in range(1, years + 1):
        cf      *= (1 + fcf_g)
        pv_fcfs += cf / ((1 + wacc) ** t)

    # Terminální hodnota (Gordonův model)
    terminal_fcf = cf * (1 + t_grow)
    terminal_val = terminal_fcf / (wacc - t_grow)
    pv_terminal  = terminal_val / ((1 + wacc) ** years)

    intrinsic_ev = pv_fcfs + pv_terminal
    equity_value = intrinsic_ev - net_debt
    price        = _safe(equity_value / shares) if shares else None

    base_conf = 0.80 if fcf > 0 else 0.35

    return {
        "model":           "dcf",
        "price":           price,
        "pv_fcfs":         pv_fcfs,
        "pv_terminal":     pv_terminal,
        "intrinsic_ev":    intrinsic_ev,
        "equity_value":    equity_value,
        "fcf":             fcf,
        "wacc":            wacc,
        "fcf_growth":      fcf_g,
        "terminal_growth": t_grow,
        "years":           years,
        "confidence":      base_conf,
    }


# =========================================================
# MODEL 3 — FCF YIELD  (přímé ocenění)
# =========================================================

def model_fcf_yield(
    fcf: float,
    net_debt: float,
    shares: float,
    target_yield: float = 0.04,
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
    wacc: float      = 0.10,
    growth: float    = 0.05,
    years: int       = 5,
    fade_rate: float = 0.15,
) -> dict:
    """
    Economic Profit (EP) model:
      EP = NOPAT − (Invested Capital × WACC)

    ROIC fade: každý rok se ROIC přibližuje k WACC o fade_rate × (ROIC − WACC).
    """
    if roic <= 0:
        return {"model": "roic_ep", "price": None, "confidence": 0.0}

    invested_capital = nopat / roic

    pv_ep     = 0.0
    ic        = invested_capital
    cur_roic  = roic

    for t in range(1, years + 1):
        ic       *= (1 + growth)
        cur_nopat = ic * cur_roic
        ep        = cur_nopat - ic * wacc
        pv_ep    += ep / ((1 + wacc) ** t)

        cur_roic -= fade_rate * (cur_roic - wacc)
        cur_roic  = max(cur_roic, wacc)

    terminal_ep      = ic * cur_roic - ic * wacc
    pv_terminal      = (terminal_ep / (wacc - 0.02)) / ((1 + wacc) ** years)

    intrinsic_equity = invested_capital + pv_ep + pv_terminal
    equity_value     = intrinsic_equity - net_debt
    price            = _safe(equity_value / shares) if shares else None
    confidence       = 0.70 if roic > wacc else 0.40

    return {
        "model":              "roic_ep",
        "price":              price,
        "invested_capital":   invested_capital,
        "pv_economic_profit": pv_ep,
        "pv_terminal":        pv_terminal,
        "equity_value":       equity_value,
        "confidence":         confidence,
    }


# =========================================================
# COMPOSITE — vážený průměr dostupných modelů
# =========================================================

MODEL_WEIGHTS = {
    "ev_ebitda": 0.50,
    "dcf":       0.30,
    "fcf_yield": 0.20,
    "roic_ep":   0.40,
}


def composite_price(models: list[dict]) -> dict:
    """
    Vážený průměr price targetů — pevné váhy podle spolehlivosti modelu.
    EV/EBITDA dostává nejvyšší váhu — vychází z reálného tržního multiple.
    """
    valid = [m for m in models if m.get("price") is not None and m.get("confidence", 0) > 0]
    if not valid:
        return {"price": None, "confidence": 0.0, "models_used": []}

    raw_weights  = {m["model"]: MODEL_WEIGHTS.get(m["model"], 0.3) for m in valid}
    total_w      = sum(raw_weights.values())
    norm_weights = {k: v / total_w for k, v in raw_weights.items()}

    w_price  = sum(m["price"] * norm_weights[m["model"]] for m in valid)
    avg_conf = sum(m["confidence"] for m in valid) / len(valid)

    return {
        "price":       _safe(w_price),
        "confidence":  min(avg_conf, 1.0),
        "models_used": [m["model"] for m in valid],
        "weights":     {k: round(v, 3) for k, v in norm_weights.items()},
    }


# =========================================================
# SCÉNÁŘOVÉ PARAMETRY
# =========================================================

SCENARIO_PARAMS = {
    "bear": {
        "revenue_growth_adj": -0.05,
        "ebitda_margin_adj":  -0.03,
        "ev_ebitda_adj":      -0.20,
        "wacc_adj":           +0.02,
        "target_yield_adj":   +0.01,
        "roic_growth_adj":    -0.02,
        "label":              "Bear",
    },
    "base": {
        "revenue_growth_adj":  0.0,
        "ebitda_margin_adj":   0.0,
        "ev_ebitda_adj":       0.0,
        "wacc_adj":            0.0,
        "target_yield_adj":    0.0,
        "roic_growth_adj":     0.0,
        "label":               "Base",
    },
    "bull": {
        "revenue_growth_adj": +0.05,
        "ebitda_margin_adj":  +0.03,
        "ev_ebitda_adj":      +0.20,
        "wacc_adj":           -0.01,
        "target_yield_adj":   -0.01,
        "roic_growth_adj":    +0.03,
        "label":              "Bull",
    },
}


# =========================================================
# RUN SCENARIOS  (hlavní entry point)
# =========================================================

def run_scenarios(
    input_data: dict,
    wacc: float = 0.10,
    years: int = 5,
    scenario_overrides: dict | None = None,
) -> dict:
    """
    Runs bear/base/bull valuation scenarios across available models.

    `scenario_overrides` může obsahovat per-scénář hodnoty z UI:
      revenue_cagr, ebitda_margin, ev_ebitda_multiple, fcf_margin

    FCF growth pro DCF se odvozuje jako:
      min(revenue_cagr_5y, net_income_cagr_5y, 0.15)
    kde obě CAGR hodnoty přichází z SEC pipeline (backend/sec.py).
    """
    revenue            = float(input_data.get("revenue") or 0)
    ebitda_margin      = float(input_data.get("ebitda_margin") or 0.20)
    ev_ebitda_multiple = float(input_data.get("ev_ebitda_multiple") or 15.0)
    net_debt           = float(input_data.get("net_debt") or 0)
    shares_raw         = input_data.get("shares")
    if not shares_raw:
        return {"error": "missing shares - cannot value company"}

    shares         = float(shares_raw)
    revenue_growth = float(input_data.get("revenue_growth") or 0.05)

    fcf = _safe(input_data.get("fcf"))
    if fcf is None:
        fcf_margin_input = _safe(input_data.get("fcf_margin"))
        if fcf_margin_input and fcf_margin_input > 0 and revenue > 0:
            fcf = revenue * fcf_margin_input

    nopat = _safe(input_data.get("nopat"))
    roic  = _safe(input_data.get("roic"))

    # ── FCF growth: konzervativní minimum z 5Y CAGR ──────────────────
    revenue_cagr_5y    = _safe(input_data.get("revenue_cagr_5y"))
    net_income_cagr_5y = _safe(input_data.get("net_income_cagr_5y"))
    candidates         = [x for x in [revenue_cagr_5y, net_income_cagr_5y] if x is not None]
    fcf_growth_base    = min(*candidates, 0.15) if candidates else revenue_growth

    scenario_overrides = scenario_overrides or {}
    result = {}

    for scenario, sp in SCENARIO_PARAMS.items():
        override    = scenario_overrides.get(scenario) or {}
        models_out  = {}

        def _override(key, default):
            v = override.get(key)
            if v is None or v == 0:
                return default
            return float(v)

        adj_growth   = _override("revenue_cagr",      revenue_growth + sp["revenue_growth_adj"])
        adj_margin   = _override("ebitda_margin",      ebitda_margin  + sp["ebitda_margin_adj"])
        adj_margin   = max(adj_margin, 0.01)
        adj_multiple = _override("ev_ebitda_multiple", ev_ebitda_multiple * (1 + sp["ev_ebitda_adj"]))
        adj_multiple = max(adj_multiple, 1.0)

        scenario_fcf = fcf
        fcf_margin   = _safe(override.get("fcf_margin"))
        if fcf_margin and fcf_margin > 0 and revenue > 0:
            scenario_fcf = revenue * ((1 + adj_growth) ** years) * fcf_margin

        # MODEL 1 — EV/EBITDA
        models_out["ev_ebitda"] = model_ev_ebitda(
            revenue=revenue,
            ebitda_margin=adj_margin,
            ev_ebitda_multiple=adj_multiple,
            net_debt=net_debt,
            shares=shares,
            revenue_growth=adj_growth,
            years=years,
        )

        # MODEL 2 + 3 — DCF + FCF Yield (pouze pokud máme FCF)
        if scenario_fcf is not None and scenario_fcf > 0:
            adj_wacc  = max(wacc + sp["wacc_adj"], 0.04)
            dcf_years = max(years, 10)

            # Scénářový adj_growth posune fcf_growth_base nahoru/dolů
            # ale stále drží konzervativní strop 0.15
            scenario_fcf_growth = min(
                fcf_growth_base + sp["revenue_growth_adj"],
                0.15,
            )

            models_out["dcf"] = model_dcf(
                fcf=scenario_fcf,
                net_debt=net_debt,
                shares=shares,
                wacc=adj_wacc,
                fcf_growth=scenario_fcf_growth,
                terminal_growth=0.025,
                years=dcf_years,
            )

            adj_yield = max(0.04 + sp["target_yield_adj"], 0.01)
            models_out["fcf_yield"] = model_fcf_yield(
                fcf=scenario_fcf,
                net_debt=net_debt,
                shares=shares,
                target_yield=adj_yield,
            )

        # MODEL 4 — ROIC/EP (pouze pokud máme nopat + roic)
        if nopat is not None and roic is not None and roic > 0 and nopat != 0:
            adj_wacc    = max(wacc + sp["wacc_adj"], 0.04)
            roic_growth = max(adj_growth + sp["roic_growth_adj"], 0.0)
            models_out["roic_ep"] = model_roic_ep(
                nopat=nopat,
                roic=roic,
                net_debt=net_debt,
                shares=shares,
                wacc=adj_wacc,
                growth=roic_growth,
                years=years,
            )

        valid_models      = [m for m in models_out.values() if m and m.get("price") is not None]
        comp              = composite_price(valid_models)
        ev_model          = models_out["ev_ebitda"]
        projected_revenue = revenue * ((1 + adj_growth) ** years)

        result[scenario] = {
            "label":               sp["label"],
            "revenue_cagr":        adj_growth,
            "ebitda_margin":       adj_margin,
            "ev_ebitda_multiple":  adj_multiple,
            "projected_revenue":   projected_revenue,
            "projected_ebitda":    ev_model.get("ebitda"),
            "exit_ev":             ev_model.get("ev"),
            "exit_price_per_share": ev_model.get("price"),
            "models":              models_out,
            "composite":           comp,
            "price":               comp["price"],
            "ebitda":              ev_model.get("ebitda"),
            "ev":                  ev_model.get("ev"),
            "equity":              ev_model.get("equity"),
        }

    return result
