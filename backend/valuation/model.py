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

Kalibrace podle typu firmy (auto-detekce z input_data):
  - mega_tech:   EBITDA margin > 30 % + revenue > 50B + growth > 8 %
  - growth_saas: revenue growth > 15 % (menší firma)
  - default:     vše ostatní

Vstupy input_data (všechny dostupné z main.py /valuation pipeline):
  revenue            float  TTM revenue [USD]             — sec / fmp
  ebitda_margin      float  TTM EBITDA / revenue          — odvozeno v main.py
  ev_ebitda_multiple float  TTM EV/EBITDA                 — compute_metrics TTM
  net_debt           float  dlouhodobý dluh - cash        — sec.extract_net_debt
  shares             float  počet akcií                   — sec
  fcf                float  TTM FCF (CFO - CapEx)         — sec.extract_fcf
  fcf_margin         float  fcf / revenue                 — odvozeno v main.py
  nopat              float  NOPAT (volitelné)             — compute_metrics
  roic               float  ROIC (volitelné)              — compute_metrics
  revenue_growth     float  3Y CAGR z history             — odvozeno v main.py
  revenue_cagr_5y    float  5Y CAGR z history.revenue    — sec.compute_cagr_5y
  net_income_cagr_5y float  5Y CAGR z history.net_income — sec.compute_cagr_5y
  tax_rate           float  efektivní daňová sazba        — compute_metrics
  cfo                float  TTM Cash From Operations      — sec.extract_cfo (nové)
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
# DETEKCE TYPU FIRMY
# =========================================================

FIRM_PROFILES = {
    "mega_tech": {
        # Kalibrace: Apple, Microsoft, Google, Meta
        "ev_ebitda_bear_adj":  -0.15,   # -15 % multiple komprese
        "ev_ebitda_bull_adj":  +0.20,
        "ev_ebitda_floor":      16.0,   # nikdy pod 16x i v bear
        "fcf_yield_base":       0.025,  # P/FCF ~40x historické ocenění
        "fcf_yield_bear":       0.035,  # P/FCF ~29x komprese sentimentu
        "fcf_yield_bull":       0.018,  # P/FCF ~56x boom ocenění
        "wacc_base":            0.09,   # nižší riziko
        "wacc_bear_adj":       +0.015,
        "wacc_bull_adj":       -0.010,
        "dcf_fcf_multiplier":   0.65,   # CFO x 0.65 = normalizovaný FCF (odstraní growth CapEx)
        "revenue_bear_adj":    -0.04,
        "revenue_bull_adj":    +0.04,
        "margin_bear_adj":     -0.02,
        "margin_bull_adj":     +0.02,
        "label":               "Mega-cap Tech",
    },
    "growth_saas": {
        # Kalibrace: Snowflake, Datadog, Cloudflare, HubSpot
        "ev_ebitda_bear_adj":  -0.25,   # vyšší volatilita ocenění
        "ev_ebitda_bull_adj":  +0.35,
        "ev_ebitda_floor":      10.0,
        "fcf_yield_base":       0.035,  # P/FCF ~29x
        "fcf_yield_bear":       0.055,  # P/FCF ~18x výrazná komprese
        "fcf_yield_bull":       0.022,  # P/FCF ~45x
        "wacc_base":            0.11,   # vyšší riziko
        "wacc_bear_adj":       +0.030,
        "wacc_bull_adj":       -0.015,
        "dcf_fcf_multiplier":   1.0,    # FCF přímo bez normalizace
        "revenue_bear_adj":    -0.06,
        "revenue_bull_adj":    +0.07,
        "margin_bear_adj":     -0.04,
        "margin_bull_adj":     +0.04,
        "label":               "Growth SaaS/Tech",
    },
    "default": {
        # Kalibrace: průměrná S&P 500 firma
        "ev_ebitda_bear_adj":  -0.20,
        "ev_ebitda_bull_adj":  +0.20,
        "ev_ebitda_floor":      6.0,
        "fcf_yield_base":       0.040,  # P/FCF ~25x
        "fcf_yield_bear":       0.055,
        "fcf_yield_bull":       0.028,
        "wacc_base":            0.10,
        "wacc_bear_adj":       +0.020,
        "wacc_bull_adj":       -0.010,
        "dcf_fcf_multiplier":   1.0,
        "revenue_bear_adj":    -0.05,
        "revenue_bull_adj":    +0.05,
        "margin_bear_adj":     -0.03,
        "margin_bull_adj":     +0.03,
        "label":               "Default",
    },
}


def detect_firm_type(
    revenue: float,
    ebitda_margin: float,
    revenue_growth: float,
) -> str:
    """
    Auto-detekce typu firmy z fundamentálních dat.

    mega_tech:   revenue > 50B + EBITDA margin > 30 % + growth > 8 %
    growth_saas: growth > 15 % (bez ohledu na velikost)
    default:     vše ostatní
    """
    is_large       = revenue > 50_000_000_000
    is_profitable  = ebitda_margin > 0.30
    is_growing     = revenue_growth > 0.08
    is_fast_growth = revenue_growth > 0.15

    if is_large and is_profitable and is_growing:
        return "mega_tech"
    if is_fast_growth:
        return "growth_saas"
    return "default"


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
    years: int = 3,
) -> dict:
    """
    Forward EV/EBITDA model.
    price = (EBITDA_forward x multiple - net_debt) / shares

    Odpovídá na otázku: "Za kolik trh ocení firmu za N let při tomto růstu?"
    """
    if not shares or shares <= 0:
        return {"model": "ev_ebitda", "price": None, "confidence": 0.0}

    rev_forward = revenue * ((1 + revenue_growth) ** years)
    ebitda      = _safe(rev_forward * ebitda_margin)
    if ebitda is None or ebitda <= 0:
        return {"model": "ev_ebitda", "price": None, "confidence": 0.0}

    ev     = ebitda * ev_ebitda_multiple
    equity = ev - net_debt
    price  = _safe(equity / shares)

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
    wacc: float            = 0.10,
    fcf_growth: float      = 0.06,
    terminal_growth: float = 0.025,
    years: int             = 10,
) -> dict:
    """
    Dvoustupňový DCF:
      Fáze 1: explicitní FCF projekce na `years` let
      Fáze 2: Gordonův model terminální hodnoty

    fcf_growth = min(revenue_cagr_5y, net_income_cagr_5y, 0.15)
    Pro mega_tech: fcf = cfo x 0.65 (normalizace growth CapEx)
    """
    if not shares or shares <= 0 or fcf <= 0:
        return {"model": "dcf", "price": None, "confidence": 0.0}

    fcf_g  = min(abs(fcf_growth), 0.35) * (1 if fcf_growth >= 0 else -1)
    t_grow = min(terminal_growth, wacc - 0.005)

    pv_fcfs = 0.0
    cf = fcf
    for t in range(1, years + 1):
        cf      *= (1 + fcf_g)
        pv_fcfs += cf / ((1 + wacc) ** t)

    terminal_fcf = cf * (1 + t_grow)
    terminal_val = terminal_fcf / (wacc - t_grow)
    pv_terminal  = terminal_val / ((1 + wacc) ** years)

    intrinsic_ev = pv_fcfs + pv_terminal
    equity_value = intrinsic_ev - net_debt
    price        = _safe(equity_value / shares)
    base_conf    = 0.80 if fcf > 0 else 0.35

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
      price = (fair_mc - net_debt) / shares

    target_yield podle typu firmy:
      mega_tech:   2.5 % base (P/FCF ~40x)
      growth_saas: 3.5 % base (P/FCF ~29x)
      default:     4.0 % base (P/FCF ~25x)
    """
    if not shares or shares <= 0 or target_yield <= 0:
        return {"model": "fcf_yield", "price": None, "confidence": 0.0}

    fair_mc      = fcf / target_yield
    equity_value = fair_mc - net_debt
    price        = _safe(equity_value / shares)
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
      EP = NOPAT - (Invested Capital x WACC)

    ROIC fade: každý rok se ROIC přibližuje k WACC.
    Vyžaduje nopat + roic z compute_metrics.
    """
    if not shares or shares <= 0 or roic <= 0 or not nopat:
        return {"model": "roic_ep", "price": None, "confidence": 0.0}

    invested_capital = nopat / roic

    pv_ep    = 0.0
    ic       = invested_capital
    cur_roic = roic

    for t in range(1, years + 1):
        ic        *= (1 + growth)
        cur_nopat  = ic * cur_roic
        ep         = cur_nopat - ic * wacc
        pv_ep     += ep / ((1 + wacc) ** t)
        cur_roic  -= fade_rate * (cur_roic - wacc)
        cur_roic   = max(cur_roic, wacc)

    terminal_ep      = ic * cur_roic - ic * wacc
    pv_terminal      = (terminal_ep / (wacc - 0.02)) / ((1 + wacc) ** years)
    intrinsic_equity = invested_capital + pv_ep + pv_terminal
    equity_value     = intrinsic_equity - net_debt
    price            = _safe(equity_value / shares)
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
    Vážený průměr price targetů.
    EV/EBITDA má nejvyšší váhu — vychází z reálného tržního multiple.
    Váhy se normalizují podle dostupných modelů.
    """
    valid = [m for m in models if m.get("price") is not None and m.get("confidence", 0) > 0]
    if not valid:
        return {"price": None, "confidence": 0.0, "models_used": []}

    raw_weights  = {m["model"]: MODEL_WEIGHTS.get(m["model"], 0.3) for m in valid}
    total_w      = sum(raw_weights.values())
    norm_weights = {k: v / total_w for k, v in raw_weights.items()}
    w_price      = sum(m["price"] * norm_weights[m["model"]] for m in valid)
    avg_conf     = sum(m["confidence"] for m in valid) / len(valid)

    return {
        "price":       _safe(w_price),
        "confidence":  min(avg_conf, 1.0),
        "models_used": [m["model"] for m in valid],
        "weights":     {k: round(v, 3) for k, v in norm_weights.items()},
    }


# =========================================================
# RUN SCENARIOS  (hlavní entry point)
# =========================================================

def run_scenarios(
    input_data: dict,
    wacc: float = 0.10,
    years: int = 3,
    scenario_overrides: dict | None = None,
) -> dict:
    """
    Runs bear/base/bull valuation scenarios across available models.

    Auto-detekuje typ firmy a kalibruje:
      - EV/EBITDA floor + adjustmenty
      - FCF yield target podle profilu
      - WACC podle rizika firmy
      - DCF FCF normalizaci (mega_tech: cfo x 0.65)

    Všechny vstupy jsou dostupné z main.py /valuation endpointu.
    Jediný nový vstup který musíš přidat do input_data v main.py: "cfo"
    """
    # ── Základní vstupy ──────────────────────────────────────────────
    revenue            = float(input_data.get("revenue") or 0)
    ebitda_margin      = float(input_data.get("ebitda_margin") or 0.20)
    ev_ebitda_multiple = float(input_data.get("ev_ebitda_multiple") or 15.0)
    net_debt           = float(input_data.get("net_debt") or 0)
    shares_raw         = input_data.get("shares")
    if not shares_raw:
        return {"error": "missing shares - cannot value company"}

    shares         = float(shares_raw)
    revenue_growth = float(input_data.get("revenue_growth") or 0.05)
    nopat          = _safe(input_data.get("nopat"))
    roic           = _safe(input_data.get("roic"))
    cfo            = _safe(input_data.get("cfo"))

    # ── FCF vstup ────────────────────────────────────────────────────
    fcf = _safe(input_data.get("fcf"))
    if fcf is None:
        fcf_margin_input = _safe(input_data.get("fcf_margin"))
        if fcf_margin_input and fcf_margin_input > 0 and revenue > 0:
            fcf = revenue * fcf_margin_input

    # ── FCF growth: min(revenue_cagr_5y, net_income_cagr_5y, 0.15) ──
    # Pouze pozitivní CAGR — záporný growth v DCF dává nereálné výsledky
    # pro stabilní firmy (PFE po Paxlovid propadu, cyklické firmy atd.)
    revenue_cagr_5y    = _safe(input_data.get("revenue_cagr_5y"))
    net_income_cagr_5y = _safe(input_data.get("net_income_cagr_5y"))
    candidates         = [
        x for x in [revenue_cagr_5y, net_income_cagr_5y]
        if x is not None and x > 0
    ]
    # Fallback 3 % = konzervativní dlouhodobý růst (GDP-like)
    fcf_growth_base    = min(*candidates, 0.15) if candidates else 0.03

    # ── Detekce typu firmy + kalibrace ───────────────────────────────
    firm_type = detect_firm_type(revenue, ebitda_margin, revenue_growth)
    profile   = FIRM_PROFILES[firm_type]

    # DCF FCF: normalizovaný pro mega_tech, přímý pro ostatní
    multiplier     = profile["dcf_fcf_multiplier"]
    normalized_fcf = None
    if firm_type == "mega_tech" and cfo is not None and cfo > 0:
        normalized_fcf = cfo * multiplier   # CFO x 0.65
    elif fcf is not None and fcf > 0:
        normalized_fcf = fcf

    scenario_overrides = scenario_overrides or {}
    result = {}

    for scenario in ("bear", "base", "bull"):
        override   = scenario_overrides.get(scenario) or {}
        models_out = {}

        def _override(key, default):
            v = override.get(key)
            if v is None or v == 0:
                return default
            return float(v)

        # ── Scénářové adjustmenty z profilu ──────────────────────────
        if scenario == "bear":
            rev_adj        = profile["revenue_bear_adj"]
            margin_adj     = profile["margin_bear_adj"]
            multiple_adj   = profile["ev_ebitda_bear_adj"]
            wacc_adj       = profile["wacc_bear_adj"]
            yield_target   = profile["fcf_yield_bear"]
            fcf_growth_adj = -0.03
        elif scenario == "bull":
            rev_adj        = profile["revenue_bull_adj"]
            margin_adj     = profile["margin_bull_adj"]
            multiple_adj   = profile["ev_ebitda_bull_adj"]
            wacc_adj       = profile["wacc_bull_adj"]
            yield_target   = profile["fcf_yield_bull"]
            fcf_growth_adj = +0.02
        else:  # base
            rev_adj        = 0.0
            margin_adj     = 0.0
            multiple_adj   = 0.0
            wacc_adj       = 0.0
            yield_target   = profile["fcf_yield_base"]
            fcf_growth_adj = 0.0

        adj_growth   = _override("revenue_cagr",      revenue_growth + rev_adj)
        adj_margin   = _override("ebitda_margin",      ebitda_margin  + margin_adj)
        adj_margin   = max(adj_margin, 0.01)

        # EV/EBITDA multiple s floor podle profilu
        raw_multiple = ev_ebitda_multiple * (1 + multiple_adj)
        adj_multiple = _override("ev_ebitda_multiple", max(raw_multiple, profile["ev_ebitda_floor"]))

        adj_wacc  = max(profile["wacc_base"] + wacc_adj, 0.04)
        dcf_years = max(years, 10)

        # FCF pro tento scénář (override z UI nebo normalizovaný)
        scenario_fcf = normalized_fcf
        fcf_margin   = _safe(override.get("fcf_margin"))
        if fcf_margin and fcf_margin > 0 and revenue > 0:
            scenario_fcf = revenue * ((1 + adj_growth) ** years) * fcf_margin

        # FCF growth: floor 0.0 — záporný growth dává nereálné DCF výsledky
        scenario_fcf_growth = min(max(fcf_growth_base + fcf_growth_adj, 0.0), 0.15)

        # ── MODEL 1: EV/EBITDA ───────────────────────────────────────
        models_out["ev_ebitda"] = model_ev_ebitda(
            revenue=revenue,
            ebitda_margin=adj_margin,
            ev_ebitda_multiple=adj_multiple,
            net_debt=net_debt,
            shares=shares,
            revenue_growth=adj_growth,
            years=years,
        )

        # ── MODEL 2 + 3: DCF + FCF Yield ────────────────────────────
        if scenario_fcf is not None and scenario_fcf > 0:
            models_out["dcf"] = model_dcf(
                fcf=scenario_fcf,
                net_debt=net_debt,
                shares=shares,
                wacc=adj_wacc,
                fcf_growth=scenario_fcf_growth,
                terminal_growth=0.025,
                years=dcf_years,
            )
            models_out["fcf_yield"] = model_fcf_yield(
                fcf=scenario_fcf,
                net_debt=net_debt,
                shares=shares,
                target_yield=yield_target,
            )

        # ── MODEL 4: ROIC/EP ─────────────────────────────────────────
        if nopat is not None and roic is not None and roic > 0 and nopat != 0:
            roic_growth = max(adj_growth + (-0.02 if scenario == "bear" else 0.0), 0.0)
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
            "label":                {"bear": "Bear", "base": "Base", "bull": "Bull"}[scenario],
            "firm_type":            firm_type,
            "firm_profile":         profile["label"],
            "revenue_cagr":         adj_growth,
            "ebitda_margin":        adj_margin,
            "ev_ebitda_multiple":   adj_multiple,
            "projected_revenue":    projected_revenue,
            "projected_ebitda":     ev_model.get("ebitda"),
            "exit_ev":              ev_model.get("ev"),
            "exit_price_per_share": ev_model.get("price"),
            "models":               models_out,
            "composite":            comp,
            "price":                comp["price"],
            "ebitda":               ev_model.get("ebitda"),
            "ev":                   ev_model.get("ev"),
            "equity":               ev_model.get("equity"),
            "dcf_fcf_used":         scenario_fcf,
            "fcf_growth_used":      scenario_fcf_growth,
            "wacc_used":            adj_wacc,
        }

    return result
