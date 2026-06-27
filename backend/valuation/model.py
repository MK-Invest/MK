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
  fcf_3y_median      float  Medián FCF za posl. 3 fisk. roky — sec.compute_fcf_median (nové)

DCF se počítá ve dvou variantách (pokud jsou data dostupná):
  - "dcf"            : TTM FCF (standardní, citlivý na jednorázové výkyvy)
  - "dcf_normalized" : 3Y mediánový FCF (robustní vůči jednorázovým propadům/
                        windfall rokům — např. PFE post-COVID, akviziční dluh)

RŮST (revenue_cagr) — uživatelem řízený vstup:
  Uživatel zadává revenue_cagr zvlášť pro bear/base/bull scénář (přes
  scenario_overrides). Toto číslo se použije KONZISTENTNĚ pro:
    - EV/EBITDA forward revenue projekci
    - DCF FCF growth (capped na 15 % — i agresivní firmy nerostou FCF
      dlouhodobě rychleji, model by jinak divergoval)
  Pokud uživatel growth nezadá, použije se automatický odhad z 5Y CAGR
  (revenue/net income historie) jako fallback — ale to je záložní chování,
  ne primární zdroj pravdy.
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


def detect_model_warnings(
    firm_type: str,
    net_debt: float,
    ebitda: float,
    fcf: float,
    revenue_cagr_5y: Optional[float],
    net_income_cagr_5y: Optional[float],
) -> list[str]:
    """
    Detekuje situace kdy je konkrétní model méně vhodný pro danou firmu.
    Nemění výpočty — jen vrací varování pro zobrazení uživateli.
    """
    warnings: list[str] = []

    # Vysoká zadluženost zkresluje DCF a FCF Yield (citlivé na net_debt)
    if ebitda and ebitda > 0 and net_debt > 0:
        leverage = net_debt / ebitda
        if leverage > 4.0:
            warnings.append(
                f"Net debt/EBITDA = {leverage:.1f}x — vysoká zadluženost. "
                f"DCF horizont byl zkrácen na 5 let (místo 10) — dlouhý "
                f"horizont u zadlužené firmy implicitně předpokládá "
                f"postupné splacení dluhu, což je u tohoto leverage "
                f"příliš optimistický předpoklad. DCF a FCF Yield zůstávají "
                f"citlivé na net_debt odečet a mohou podhodnocovat firmu, "
                f"pokud je dluh dočasný (např. po akvizici)."
            )

    # Nízký nebo záporný FCF vůči EBITDA (CapEx/úroky stlačují cash generation)
    if ebitda and ebitda > 0 and fcf is not None:
        fcf_conversion = fcf / ebitda
        if fcf_conversion < 0.25:
            warnings.append(
                f"FCF/EBITDA konverze = {fcf_conversion:.0%} — neobvykle nízká. "
                f"DCF a FCF Yield mohou vycházet z dočasně stlačeného FCF "
                f"(vysoký CapEx, úrokové náklady, jednorázové položky)."
            )

    # Záporné historické CAGR — TTM FCF nemusí být reprezentativní
    if (revenue_cagr_5y is not None and revenue_cagr_5y < 0) or \
       (net_income_cagr_5y is not None and net_income_cagr_5y < 0):
        warnings.append(
            "Historický 5Y CAGR (revenue nebo net income) je záporný. "
            "DCF growth byl ořezán na konzervativní fallback (3 %) — "
            "TTM čísla mohou odrážet dočasný pokles, ne strukturální trend."
        )

    return warnings


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
    wacc: float = 0.10,
) -> dict:
    """
    Forward EV/EBITDA model s diskontováním exit hodnoty zpět k dnešku.

    Dvě fáze:
      1. Projekce: EBITDA_exit = revenue × (1+g)^N × margin
                   exit_equity = EBITDA_exit × multiple - net_debt
                   exit_price  = exit_equity / shares  (cena za N let)
      2. Diskontování: pv_price = exit_price / (1 + wacc)^N  (dnešní PV)

    KLÍČOVÝ ROZDÍL oproti původní verzi:
      Původní 'price' byla exit cena za N let — nešla přímo porovnávat
      s aktuální cenou akcie bez dalšího kroku. Investoři kupují DNES,
      takže potřebují PV (kolik exit stojí dnes při požadovaném výnosu).

      'exit_price' zůstává v outputu pro transparentnost (a frontend
      ji zobrazuje jako 'required_cagr' pohled — jak rychle musím
      cena růst od dneška k exit hodnotě).

    Odpovídá na otázku: "Kolik je firma férově oceněná DNES, pokud za
    N let bude obchodovat na daném multiple při tomto growth a já chci
    ročně vydělat WACC%?"
    """
    if not shares or shares <= 0:
        return {"model": "ev_ebitda", "price": None, "confidence": 0.0}

    rev_forward = revenue * ((1 + revenue_growth) ** years)
    ebitda      = _safe(rev_forward * ebitda_margin)
    if ebitda is None or ebitda <= 0:
        return {"model": "ev_ebitda", "price": None, "confidence": 0.0}

    ev          = ebitda * ev_ebitda_multiple
    equity      = ev - net_debt
    exit_price  = _safe(equity / shares)

    # Diskontuj exit hodnotu zpět k dnešku přes WACC
    discount    = (1 + wacc) ** years
    pv_price    = _safe(exit_price / discount) if exit_price is not None else None

    return {
        "model":            "ev_ebitda",
        "price":            pv_price,       # ← PV k dnešku — srovnatelné s aktuální cenou
        "exit_price":       exit_price,     # ← cena za N let (pro required_cagr výpočet)
        "ebitda":           ebitda,
        "ev":               ev,
        "equity":           equity,
        "wacc":             wacc,
        "years":            years,
        "discount_factor":  discount,
        "confidence":       0.55,
    }


# =========================================================
# MODEL 2 — DCF  (diskontované FCF)
# =========================================================

def model_dcf_short(
    fcf: float,
    ebitda: float,
    net_debt: float,
    shares: float,
    wacc: float            = 0.10,
    fcf_growth: float       = 0.10,
    exit_multiple: float    = 15.0,
    years: int              = 3,
) -> dict:
    """
    Krátkodobý DCF pro trading horizont (ne investiční DCF).

    Na rozdíl od model_dcf NEPOUŽÍVÁ Gordonův model terminální hodnoty
    (která implicitně předpokládá nekonečný růst a u krátkého horizontu
    začne tvořit 80-90%+ výsledné ceny — viz analýza: s years=3 by
    klasický DCF byl prakticky jen sázka na terminal_growth/wacc, ne na
    skutečnou fundamentální projekci).

    Místo toho:
      Fáze 1: explicitní FCF za `years` let, diskontované k dnešku
      Fáze 2: "exit hodnota" = projected EBITDA (za `years` let) x exit_multiple
              — stejná logika jako EV/EBITDA model, ne nekonečná řada

    Odpovídá na otázku: "Pokud firma poroste `fcf_growth` ročně a za
    `years` let ji koupí/ocení trh na `exit_multiple` EBITDA, kolik je
    fér zaplatit dnes?" — to je otázka tradera s krátkým horizontem,
    ne investora počítajícího perpetuitu.
    """
    if not shares or shares <= 0 or fcf <= 0 or not ebitda or ebitda <= 0:
        return {"model": "dcf_short", "price": None, "confidence": 0.0}

    fcf_g = min(abs(fcf_growth), 0.60) * (1 if fcf_growth >= 0 else -1)

    pv_fcfs = 0.0
    cf = fcf
    ebitda_proj = ebitda
    for t in range(1, years + 1):
        cf          *= (1 + fcf_g)
        ebitda_proj *= (1 + fcf_g)
        pv_fcfs     += cf / ((1 + wacc) ** t)

    exit_ev      = ebitda_proj * exit_multiple
    pv_exit      = exit_ev / ((1 + wacc) ** years)

    intrinsic_ev = pv_fcfs + pv_exit
    equity_value = intrinsic_ev - net_debt
    price        = _safe(equity_value / shares)
    base_conf    = 0.75 if fcf > 0 else 0.30

    return {
        "model":              "dcf_short",
        "price":              price,
        "pv_fcfs":            pv_fcfs,
        "pv_exit":            pv_exit,
        "projected_ebitda":   ebitda_proj,
        "exit_ev":            exit_ev,
        "intrinsic_ev":       intrinsic_ev,
        "equity_value":       equity_value,
        "fcf":                fcf,
        "wacc":               wacc,
        "fcf_growth":         fcf_g,
        "exit_multiple":      exit_multiple,
        "years":              years,
        "confidence":         base_conf,
    }


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
    Dvoustupňový DCF (klasický, investiční horizont):
      Fáze 1: explicitní FCF projekce na `years` let
      Fáze 2: Gordonův model terminální hodnoty

    fcf_growth: typicky uživatelův vstup (revenue_cagr per scénář) nebo
    fallback z historických 5Y CAGR dat. Pro mega_tech: fcf = cfo x 0.65
    (normalizace growth CapEx).

    Interní safety cap 60 % chrání jen proti overflow/překlepu — legitimně
    agresivní odhady (např. 30% meziroční růst z analytického reportu)
    musí projít beze změny, model je nemá potichu ořezávat.

    POZNÁMKA: pro krátký trading horizont (1-3 roky) preferuj
    model_dcf_short — Gordonův model zde tvoří 80%+ výsledné ceny a
    výsledek pak odráží hlavně terminal_growth/wacc, ne skutečnou
    fundamentální projekci firmy.
    """
    if not shares or shares <= 0 or fcf <= 0:
        return {"model": "dcf", "price": None, "confidence": 0.0}

    fcf_g  = min(abs(fcf_growth), 0.60) * (1 if fcf_growth >= 0 else -1)
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
# MODEL 5 — P/E EXIT  (exit hodnota přes čistý zisk)
# =========================================================

def model_pe_exit(
    revenue: float,
    net_margin: float,
    pe_multiple: float,
    net_debt: float,
    shares: float,
    revenue_growth: float = 0.0,
    years: int = 3,
    wacc: float = 0.10,
) -> dict:
    """
    P/E exit model — projektuje čistý zisk za N let a ocení ho P/E multiplem.
    Výsledná exit market cap se diskontuje zpět k dnešku přes WACC.

    Logika:
      net_income_exit = revenue × (1+g)^N × net_margin
      exit_mc         = net_income_exit × pe_multiple
      exit_equity     = exit_mc - net_debt
      exit_price      = exit_equity / shares
      pv_price        = exit_price / (1 + wacc)^N

    Vhodný primárně pro:
      - profitabilní growth firmy (tech, SaaS) kde P/E je primární kotva
      - firmy kde EV/EBITDA je méně spolehlivý (high D&A, leasing adjustments)

    Méně vhodný pro:
      - firmy se záporným nebo volatilním čistým ziskem (cyclicals, turnarounds)
      - firmy s velkými jednorázovými položkami (M&A write-offs jako PFE 2023)
    """
    if not shares or shares <= 0 or net_margin <= 0 or pe_multiple <= 0:
        return {"model": "pe_exit", "price": None, "confidence": 0.0}

    rev_forward      = revenue * ((1 + revenue_growth) ** years)
    net_income_exit  = _safe(rev_forward * net_margin)
    if net_income_exit is None or net_income_exit <= 0:
        return {"model": "pe_exit", "price": None, "confidence": 0.0}

    exit_mc    = net_income_exit * pe_multiple
    exit_eq    = exit_mc - net_debt
    exit_price = _safe(exit_eq / shares)

    discount   = (1 + wacc) ** years
    pv_price   = _safe(exit_price / discount) if exit_price is not None else None

    confidence = 0.60 if net_margin > 0.05 else 0.35

    return {
        "model":             "pe_exit",
        "price":             pv_price,
        "exit_price":        exit_price,
        "net_income_exit":   net_income_exit,
        "exit_mc":           exit_mc,
        "net_margin":        net_margin,
        "pe_multiple":       pe_multiple,
        "wacc":              wacc,
        "years":             years,
        "confidence":        confidence,
    }


# =========================================================
# MODEL 6 — P/FCF EXIT  (exit hodnota přes free cash flow)
# =========================================================

def model_pfcf_exit(
    revenue: float,
    fcf_margin: float,
    pfcf_multiple: float,
    net_debt: float,
    shares: float,
    revenue_growth: float = 0.0,
    years: int = 3,
    wacc: float = 0.10,
) -> dict:
    """
    P/FCF exit model — projektuje FCF za N let a ocení ho P/FCF multiplem.
    Výsledná exit market cap se diskontuje zpět k dnešku přes WACC.

    Logika:
      fcf_exit    = revenue × (1+g)^N × fcf_margin
      exit_mc     = fcf_exit × pfcf_multiple
      exit_equity = exit_mc - net_debt
      exit_price  = exit_equity / shares
      pv_price    = exit_price / (1 + wacc)^N

    Rozdíl od model_fcf_yield:
      fcf_yield bere TTM FCF staticky (bez growth projekce) a dělí
      target yieldem → jednoduchá statická kotva "je akcie drahá dnes?"
      pfcf_exit projektuje FCF do budoucna a diskontuje zpět → dynamická
      forward-looking metrika (stejná logika jako EV/EBITDA exit model).

    Vhodný primárně pro:
      - FCF-generující growth firmy (mega-cap tech, SaaS se zralou marží)
      - firmy kde FCF > čistý zisk (D&A efekt, CapEx lehké byznysy)
      - jako cross-check k EV/EBITDA (obě metodologie by měly dát podobný výsledek)
    """
    if not shares or shares <= 0 or fcf_margin <= 0 or pfcf_multiple <= 0:
        return {"model": "pfcf_exit", "price": None, "confidence": 0.0}

    rev_forward = revenue * ((1 + revenue_growth) ** years)
    fcf_exit    = _safe(rev_forward * fcf_margin)
    if fcf_exit is None or fcf_exit <= 0:
        return {"model": "pfcf_exit", "price": None, "confidence": 0.0}

    exit_mc    = fcf_exit * pfcf_multiple
    exit_eq    = exit_mc - net_debt
    exit_price = _safe(exit_eq / shares)

    discount   = (1 + wacc) ** years
    pv_price   = _safe(exit_price / discount) if exit_price is not None else None

    confidence = 0.65 if fcf_margin > 0.05 else 0.35

    return {
        "model":          "pfcf_exit",
        "price":          pv_price,
        "exit_price":     exit_price,
        "fcf_exit":       fcf_exit,
        "exit_mc":        exit_mc,
        "fcf_margin":     fcf_margin,
        "pfcf_multiple":  pfcf_multiple,
        "wacc":           wacc,
        "years":          years,
        "confidence":     confidence,
    }



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
    "ev_ebitda":  0.50,
    "dcf":        0.30,
    "fcf_yield":  0.20,
    "roic_ep":    0.40,
    "pe_exit":    0.35,   # P/E exit — spolehlivý pro profitabilní firmy
    "pfcf_exit":  0.40,   # P/FCF exit — nejčistší cash-based exit model
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
    # ── Základní vstupy (všechny dostupné v main.py) ─────────────────
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
    fcf_3y_median  = _safe(input_data.get("fcf_3y_median"))

    # P/E exit model — net marže z dat (net_income / revenue)
    net_income_ttm = _safe(input_data.get("net_income"))
    net_margin_base = (net_income_ttm / revenue) if (net_income_ttm and revenue > 0) else None

    # P/FCF exit model — FCF marže z dat (fcf / revenue)
    fcf_raw = _safe(input_data.get("fcf"))
    pfcf_margin_base = (fcf_raw / revenue) if (fcf_raw and revenue > 0) else None

    # P/E a P/FCF múltiples — odvozené z TTM tržních metrik
    # ev_ebitda_multiple je dostupné z input_data, PE/PFCF musíme odvodit
    # z market_cap (price × shares) pokud jsou k dispozici, jinak sektorové defaulty
    price_per_share = _safe(input_data.get("price"))
    mc = price_per_share * float(shares_raw) if price_per_share else None
    pe_multiple_base  = (mc / net_income_ttm) if (mc and net_income_ttm and net_income_ttm > 0) else None
    pfcf_multiple_base = (mc / fcf_raw) if (mc and fcf_raw and fcf_raw > 0) else None

    # Sanitace — extrémní multiples (>200) jsou nesmyslné pro projekci
    if pe_multiple_base and (pe_multiple_base > 200 or pe_multiple_base < 0):
        pe_multiple_base = None
    if pfcf_multiple_base and (pfcf_multiple_base > 200 or pfcf_multiple_base < 0):
        pfcf_multiple_base = None

    # ── FCF vstup ────────────────────────────────────────────────────
    fcf = _safe(input_data.get("fcf"))
    if fcf is None:
        fcf_margin_input = _safe(input_data.get("fcf_margin"))
        if fcf_margin_input and fcf_margin_input > 0 and revenue > 0:
            fcf = revenue * fcf_margin_input

    # ── FCF growth fallback (jen pokud uživatel nezadá vlastní revenue_cagr) ──
    # Toto je ZÁLOŽNÍ odhad z historických dat. Pokud uživatel zadá vlastní
    # revenue_cagr pro scénář (přes scenario_overrides), použije se TO číslo
    # konzistentně pro EV/EBITDA i DCF — viz smyčka níže.
    revenue_cagr_5y    = _safe(input_data.get("revenue_cagr_5y"))
    net_income_cagr_5y = _safe(input_data.get("net_income_cagr_5y"))
    candidates         = [x for x in [revenue_cagr_5y, net_income_cagr_5y] if x is not None and x > 0]
    fcf_growth_fallback = min(*candidates, 0.15) if candidates else 0.03

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

    # Druhý FCF vstup pro dcf_normalized model — 3Y medián
    # Pro mega_tech firmy pořád preferujeme cfo x multiplier (growth CapEx normalizace
    # je jiný typ úpravy než vyhlazení jednorázových výkyvů, oba mohou koexistovat)
    fcf_for_median_model = None
    if firm_type == "mega_tech" and cfo is not None and cfo > 0:
        fcf_for_median_model = cfo * multiplier
    elif fcf_3y_median is not None and fcf_3y_median > 0:
        fcf_for_median_model = fcf_3y_median

    # ── Model warnings (jednou za firmu, ne per-scénář) ──────────────
    # Použij TTM EBITDA (base margin x revenue) jako referenci pro leverage/conversion checky
    ttm_ebitda_ref = revenue * ebitda_margin if revenue and ebitda_margin else None
    model_warnings = detect_model_warnings(
        firm_type=firm_type,
        net_debt=net_debt,
        ebitda=ttm_ebitda_ref,
        fcf=fcf,
        revenue_cagr_5y=revenue_cagr_5y,
        net_income_cagr_5y=net_income_cagr_5y,
    )

    # ── DCF horizont podle zadluženosti ──────────────────────────────
    # Vysoce zadlužené firmy (net_debt/EBITDA > 4x): kratší horizont (5 let).
    # 10letý DCF u silně zadlužené firmy implicitně předpokládá dlouhé
    # postupné splácení dluhu z FCF, což je přehnaně optimistický předpoklad.
    # Kratší horizont dá konzervativnější, ale realističtější obrázek.
    high_leverage = (
        ttm_ebitda_ref is not None and ttm_ebitda_ref > 0
        and net_debt > 0
        and (net_debt / ttm_ebitda_ref) > 4.0
    )
    base_dcf_years = 5 if high_leverage else 10

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

        # ── Scénářové adjustmenty z profilu (multiple/WACC/yield/margin) ──
        # Tyto zůstávají firma-typ specifické (mega_tech/growth_saas/default).
        # Growth (revenue_cagr) NENÍ součástí profilu — je to buď uživatelův
        # vstup, nebo fallback z historických dat (viz níže).
        if scenario == "bear":
            margin_adj     = profile["margin_bear_adj"]
            multiple_adj   = profile["ev_ebitda_bear_adj"]
            wacc_adj       = profile["wacc_bear_adj"]
            yield_target   = profile["fcf_yield_bear"]
            fallback_growth_adj = -0.03   # fallback-only posun, pokud uživatel nezadal nic
        elif scenario == "bull":
            margin_adj     = profile["margin_bull_adj"]
            multiple_adj   = profile["ev_ebitda_bull_adj"]
            wacc_adj       = profile["wacc_bull_adj"]
            yield_target   = profile["fcf_yield_bull"]
            fallback_growth_adj = +0.02
        else:  # base
            margin_adj     = 0.0
            multiple_adj   = 0.0
            wacc_adj       = 0.0
            yield_target   = profile["fcf_yield_base"]
            fallback_growth_adj = 0.0

        # ── RŮST: uživatelův vstup je jediný zdroj pravdy, pokud je zadaný ──
        # scenario_overrides[scenario]["revenue_cagr"] — pokud uživatel zadá
        # číslo (i 0% nebo záporné, pokud to explicitně chce), použije se
        # PŘESNĚ to, konzistentně pro EV/EBITDA i DCF.
        user_growth = override.get("revenue_cagr")
        if user_growth is not None:
            adj_growth = float(user_growth)
        else:
            # Fallback: žádný uživatelský vstup → historický odhad ± scénářový posun
            adj_growth = revenue_growth + fallback_growth_adj

        adj_margin   = _override("ebitda_margin", ebitda_margin + margin_adj)
        adj_margin   = max(adj_margin, 0.01)

        # EV/EBITDA multiple s floor podle profilu
        raw_multiple = ev_ebitda_multiple * (1 + multiple_adj)
        adj_multiple = _override("ev_ebitda_multiple", max(raw_multiple, profile["ev_ebitda_floor"]))

        adj_wacc  = max(profile["wacc_base"] + wacc_adj, 0.04)
        dcf_years = max(years, base_dcf_years)

        # FCF pro tento scénář (override z UI nebo normalizovaný)
        scenario_fcf = normalized_fcf
        fcf_margin   = _safe(override.get("fcf_margin"))
        if fcf_margin and fcf_margin > 0 and revenue > 0:
            scenario_fcf = revenue * ((1 + adj_growth) ** years) * fcf_margin

        # FCF pro dcf_normalized model (3Y medián, mega_tech: cfo x multiplier)
        scenario_fcf_3y = fcf_for_median_model
        if fcf_margin and fcf_margin > 0 and revenue > 0:
            scenario_fcf_3y = scenario_fcf  # override platí pro oba DCF varianty stejně

        # FCF growth pro DCF: STEJNÉ číslo jako adj_growth (uživatelův revenue_cagr).
        #
        # Uživatelův vstup: cap na ±60 % jako pojistka proti overflow/překlepu
        # (ne proti legitimně agresivním NEBO negativním odhadům — pokud
        # uživatel vědomě zadá bear scénář s poklesem -15 %, model to musí
        # respektovat, ne ho tiše přepsat na 0 %. Floor 0.0 dával smysl jen
        # jako ochrana automatického fallbacku, ne jako cenzura vlastního
        # úsudku uživatele).
        #
        # Fallback odhad (bez uživatelského vstupu): floor 0.0 + cap 15 %
        # zůstává — to je konzervativní pojistka pro automaticky odvozený
        # růst z historických dat, kde nechceme, aby šumové 5Y CAGR
        # vygenerovalo nereálné DCF (viz PFE — záporný 5Y CAGR z dat
        # zkreslených jednorázovým poklesem).
        if user_growth is not None:
            g = float(user_growth)
            scenario_fcf_growth = max(min(g, 0.60), -0.60)
        else:
            scenario_fcf_growth = min(max(fcf_growth_fallback + fallback_growth_adj, 0.0), 0.15)

        # ── MODEL 1: EV/EBITDA ───────────────────────────────────────
        models_out["ev_ebitda"] = model_ev_ebitda(
            revenue=revenue,
            ebitda_margin=adj_margin,
            ev_ebitda_multiple=adj_multiple,
            net_debt=net_debt,
            shares=shares,
            revenue_growth=adj_growth,
            years=years,
            wacc=adj_wacc,
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

        # ── MODEL 2b: DCF normalizovaný (3Y medián FCF) ──────────────
        # Robustní vůči jednorázovým výkyvům TTM FCF (akviziční dluh,
        # COVID windfall roky apod.). Zobrazuje se vedle standardního DCF,
        # nenahrazuje ho — uživatel vidí oba pohledy.
        if scenario_fcf_3y is not None and scenario_fcf_3y > 0:
            models_out["dcf_normalized"] = model_dcf(
                fcf=scenario_fcf_3y,
                net_debt=net_debt,
                shares=shares,
                wacc=adj_wacc,
                fcf_growth=scenario_fcf_growth,
                terminal_growth=0.025,
                years=dcf_years,
            )
            models_out["dcf_normalized"]["fcf_source"] = "3y_median"

        # ── MODEL 2c: DCF krátký horizont (trading, ne investice) ────
        # Bez Gordonova modelu — exit hodnota = projected EBITDA x multiple,
        # stejná logika jako EV/EBITDA model. Horizont capped na 3 roky
        # bez ohledu na 'years' parametr požadavku — pro delší horizont
        # použij standardní 'dcf' nebo 'dcf_normalized'.
        if scenario_fcf is not None and scenario_fcf > 0:
            short_years = min(years, 3)
            models_out["dcf_short"] = model_dcf_short(
                fcf=scenario_fcf,
                ebitda=revenue * adj_margin,  # TTM EBITDA base, projektuje se uvnitř modelu
                net_debt=net_debt,
                shares=shares,
                wacc=adj_wacc,
                fcf_growth=scenario_fcf_growth,
                exit_multiple=adj_multiple,
                years=short_years,
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

        # ── MODEL 5: P/E EXIT ────────────────────────────────────────
        # Scénářová marže — zachovává stejný poměr změny jako EBITDA margin adj
        # (přibližná heuristika: čistá marže se mění podobně jako EBITDA marže)
        if net_margin_base is not None and net_margin_base > 0:
            margin_delta = adj_margin - ebitda_margin   # jak moc se marže posouvá v daném scénáři
            adj_net_margin = max(net_margin_base + margin_delta * 0.5, 0.01)

            # P/E multiple — scénářový posun stejně jako EV/EBITDA multiple
            if pe_multiple_base is not None:
                adj_pe = max(pe_multiple_base * (1 + multiple_adj), 1.0)
                models_out["pe_exit"] = model_pe_exit(
                    revenue=revenue,
                    net_margin=adj_net_margin,
                    pe_multiple=adj_pe,
                    net_debt=net_debt,
                    shares=shares,
                    revenue_growth=adj_growth,
                    years=years,
                    wacc=adj_wacc,
                )

        # ── MODEL 6: P/FCF EXIT ──────────────────────────────────────
        if pfcf_margin_base is not None and pfcf_margin_base > 0:
            # FCF marže — mírně konzervativnější posun než EBITDA (FCF je volatilnější)
            margin_delta = adj_margin - ebitda_margin
            adj_pfcf_margin = max(pfcf_margin_base + margin_delta * 0.4, 0.01)

            if pfcf_multiple_base is not None:
                adj_pfcf = max(pfcf_multiple_base * (1 + multiple_adj), 1.0)
                models_out["pfcf_exit"] = model_pfcf_exit(
                    revenue=revenue,
                    fcf_margin=adj_pfcf_margin,
                    pfcf_multiple=adj_pfcf,
                    net_debt=net_debt,
                    shares=shares,
                    revenue_growth=adj_growth,
                    years=years,
                    wacc=adj_wacc,
                )

        # Composite se počítá jen z původní sady modelů (ev_ebitda, dcf,
        # fcf_yield, roic_ep) — dcf_normalized je doplňkový pohled a
        # nesmí změnit composite cenu u firem, kde už dnes funguje správně.
        #
        # VÝJIMKA pro vysoce zadlužené firmy (high_leverage): klasický
        # 'dcf' s Gordonovým modelem strukturálně podhodnocuje firmy kde
        # net_debt je velký vůči EV — odečet celého dluhu najednou často
        # dá zápornou cenu i při rozumném growth (viz PFE: net_debt 66B
        # vs EV ~200-500B). 'dcf_short' řeší stejnou otázku (krátký
        # horizont, exit na multiple) bez tohoto zkreslení, takže composite
        # pro tyto firmy použije dcf_short namísto dcf — stejná váha (30 %),
        # jen spolehlivější zdrojový model. Pro běžné (nezadlužené) firmy
        # se composite chová identicky jako dřív.
        composite_keys = {"ev_ebitda", "dcf", "fcf_yield", "roic_ep", "pe_exit", "pfcf_exit"}
        models_for_composite = dict(models_out)
        if high_leverage and "dcf_short" in models_out and models_out["dcf_short"].get("price") is not None:
            models_for_composite["dcf"] = models_out["dcf_short"]

        valid_models = [
            m for k, m in models_for_composite.items()
            if k in composite_keys and m and m.get("price") is not None
        ]
        comp              = composite_price(valid_models)
        ev_model          = models_out["ev_ebitda"]
        projected_revenue = revenue * ((1 + adj_growth) ** years)

        result[scenario] = {
            "label":                {"bear": "Bear", "base": "Base", "bull": "Bull"}[scenario],
            "firm_type":            firm_type,
            "firm_profile":         profile["label"],
            "revenue_cagr":         adj_growth,
            "growth_source":        "user" if user_growth is not None else "fallback",
            "ebitda_margin":        adj_margin,
            "ev_ebitda_multiple":   adj_multiple,
            "projected_revenue":    projected_revenue,
            "projected_ebitda":     ev_model.get("ebitda"),
            "exit_ev":              ev_model.get("ev"),
            # exit_price_per_share = nediskontovaná cena za N let (pro required_cagr v main.py)
            "exit_price_per_share": ev_model.get("exit_price"),
            # pv_price = diskontovaná PV k dnešku — srovnatelná s aktuální cenou
            "pv_price":             ev_model.get("price"),
            "models":               models_out,
            "composite":            comp,
            "price":                comp["price"],
            "ebitda":               ev_model.get("ebitda"),
            "ev":                   ev_model.get("ev"),
            "equity":               ev_model.get("equity"),
            "dcf_fcf_used":         scenario_fcf,
            "fcf_growth_used":      scenario_fcf_growth,
            "wacc_used":            adj_wacc,
            "dcf_years_used":       dcf_years,
            "high_leverage":        high_leverage,
            "warnings":             model_warnings,
        }

    return result
