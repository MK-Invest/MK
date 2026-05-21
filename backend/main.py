import asyncio
import os
import math
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

load_dotenv()

app = FastAPI(title="StockLens API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

FMP_STABLE = "https://financialmodelingprep.com/stable"
API_KEY = os.getenv("FMP_API_KEY", "")


import time

_cache = {}

CACHE_TTL = 300  # 5 minut

def get_cache(key):
    v = _cache.get(key)
    if not v:
        return None
    if time.time() - v["time"] > CACHE_TTL:
        del _cache[key]
        return None
    return v["data"]

def set_cache(key, data):
    _cache[key] = {"data": data, "time": time.time()}

# ---------------------------------------------------------------------------
# FMP helper
# ---------------------------------------------------------------------------


async def fmp(client: httpx.AsyncClient, path: str, params: dict = None):
    p = dict(params or {})
    p["apikey"] = API_KEY
    r = await client.get(f"{FMP_STABLE}{path}", params=p)
    r.raise_for_status()
    data = r.json()
    if isinstance(data, dict) and "Error Message" in data:
        raise HTTPException(status_code=402, detail=data["Error Message"])
    return data


# ---------------------------------------------------------------------------
# Scenario valuation model
# ---------------------------------------------------------------------------

def compute_scenario(
    *,
    revenue: float,          # Aktuální tržby (LTM)
    revenue_cagr: float,     # Růst tržeb pro tento scénář
    ebitda_margin: float,    # EBITDA marže pro tento scénář
    ev_ebitda_multiple: float,  # EV/EBITDA exit multiple
    net_debt: float,         # Čistý dluh (debt - cash)
    shares: float,           # Počet akcií
    price: float,            # Aktuální cena akcie
    required_return: float,  # Požadovaný roční výnos (diskontní sazba)
    years: int,              # Počet let projekce
) -> dict:
    """
    Exit-multiple valuace pro jeden scénář.
    Vrací kompletní výstup: projected revenue, EBITDA, EV, exit cena,
    intrinsic value dnes, upside/downside, required CAGR.
    """
    # Projekce tržeb
    projected_revenue = revenue * (1 + revenue_cagr) ** years

    # Projected EBITDA
    projected_ebitda = projected_revenue * ebitda_margin

    # Exit Enterprise Value
    exit_ev = projected_ebitda * ev_ebitda_multiple

    # Equity value = EV - čistý dluh
    exit_equity = exit_ev - net_debt

    # Exit cena na akcii
    exit_price_per_share = exit_equity / shares if shares else 0.0

    # Intrinsic value dnes = exit cena diskontovaná zpět
    intrinsic_value = exit_price_per_share / (1 + required_return) ** years

    # Upside / downside vůči aktuální ceně
    upside = (intrinsic_value / price - 1) if price else 0.0

    # Required CAGR: jaký roční výnos musí akcie dodat z aktuální ceny do exit ceny
    if price > 0 and exit_price_per_share > 0:
        required_cagr = (exit_price_per_share / price) ** (1 / years) - 1
    else:
        required_cagr = 0.0

    return {
        "revenue_cagr": round(revenue_cagr, 4),
        "ebitda_margin": round(ebitda_margin, 4),
        "ev_ebitda_multiple": round(ev_ebitda_multiple, 1),
        "projected_revenue": round(projected_revenue, 0),
        "projected_ebitda": round(projected_ebitda, 0),
        "exit_ev": round(exit_ev, 0),
        "exit_price_per_share": round(exit_price_per_share, 2),
        "intrinsic_value": round(intrinsic_value, 2),
        "upside": round(upside, 4),
        "required_cagr": round(required_cagr, 4),
    }


def compute_scenarios(
    *,
    revenue: float,
    net_debt: float,
    shares: float,
    price: float,
    # Scénáře — každý má: revenue_cagr, ebitda_margin, ev_ebitda_multiple
    bear: dict,
    base: dict,
    bull: dict,
    required_return: float,
    years: int,
) -> dict:
    """Spočítá bear / base / bull scénář a přidá hodnocení."""
    common = dict(
        revenue=revenue,
        net_debt=net_debt,
        shares=shares,
        price=price,
        required_return=required_return,
        years=years,
    )

    results = {}
    for name, params in [("bear", bear), ("base", base), ("bull", bull)]:
        results[name] = compute_scenario(
            **common,
            revenue_cagr=params["revenue_cagr"],
            ebitda_margin=params["ebitda_margin"],
            ev_ebitda_multiple=params["ev_ebitda_multiple"],
        )

    # Hodnocení: porovnej aktuální cenu s base intrinsic value
    base_iv = results["base"]["intrinsic_value"]
    base_upside = results["base"]["upside"]

    if base_upside >= 0.30:
        rating = "STRONG BUY"
        rating_color = "green"
    elif base_upside >= 0.10:
        rating = "BUY"
        rating_color = "green"
    elif base_upside >= -0.10:
        rating = "HOLD"
        rating_color = "amber"
    elif base_upside >= -0.25:
        rating = "UNDERPERFORM"
        rating_color = "red"
    else:
        rating = "SELL"
        rating_color = "red"

    confidence = (
        (1 if shares else 0) +
        (1 if revenue else 0) +
        (1 if price else 0)
    ) / 3

    return {
        "ticker": None,           # doplní endpoint
        "price": price,
        "required_return": required_return,
        "years": years,
        "net_debt": round(net_debt, 0),
        "shares": round(shares, 0),
        "scenarios": results,
        "rating": rating,
        "rating_color": rating_color,
    }


def compute_score(upside: float, margin: float, growth: float) -> float:
    """Composite score: 40 % upside, 30 % margin, 30 % growth (all as ratios)."""
    return round((upside * 40 + margin * 30 + growth * 30) * 100, 1)


# ---------------------------------------------------------------------------
# Data fetching + cache
# ---------------------------------------------------------------------------

async def _fetch_valuation_data(client: httpx.AsyncClient, ticker: str) -> dict:
    """Fetch all data needed for valuation. Results are cached per ticker."""
    
    cached = get_cache(ticker)
    if cached:
        return cached

    income, profile, balance = await asyncio.gather(
        fmp(client, "/income-statement", {"symbol": ticker, "limit": 4}),
        fmp(client, "/profile", {"symbol": ticker}),
        fmp(client, "/balance-sheet-statement", {"symbol": ticker, "limit": 1}),
    )

    if not income or not profile or not balance:
        raise HTTPException(status_code=502, detail=f"Incomplete data for {ticker}")
    
    prof = profile[0] if isinstance(profile, list) and profile else {}
    inc0 = income[0] if isinstance(income, list) and income else {}
    bal0 = balance[0] if isinstance(balance, list) and balance else {}
    revenue = float(inc0.get("revenue") or 0)
    price = float(prof.get("price") or 0)

    shares = (
        prof.get("sharesOutstanding")
        or inc0.get("weightedAverageShsOut")
        or inc0.get("weightedAverageShsOutDil")
    )

# fallback API
    if not shares:
        try:
            key_metrics = await fmp(client, "/key-metrics", {"symbol": ticker, "limit": 1})
            km0 = key_metrics[0] if isinstance(key_metrics, list) and key_metrics else {}
            shares = km0.get("sharesOutstanding")
        except:
            pass

    if not shares or shares <= 0:
        raise HTTPException(status_code=500, detail="Missing shares data")

    income_list = income if isinstance(income, list) else [income]

    # Průměrná EBITDA marže z dostupných let
    
    margins = [
        x["ebitda"] / x["revenue"]
        for x in income_list
        if x.get("revenue") and x.get("ebitda") is not None
    ]

    margins = sorted(margins)

    avg_margin = margins[len(margins)//2] if margins else 0.0

    # Historický CAGR tržeb
    
    try:
        hist_cagr = (income_list[0]["revenue"] / income_list[-1]["revenue"]) ** (
            1 / max(len(income_list) - 1, 1)
        ) - 1
        hist_cagr = max(min(hist_cagr, 0.25), -0.1)
    except (KeyError, ZeroDivisionError, TypeError):
        hist_cagr = 0.1


    net_debt = bal0.get("totalDebt", 0) - bal0.get("cashAndCashEquivalents", 0)

    # EV/EBITDA z ratios-ttm (best effort)
    ev_ebitda_ttm = None
    try:
        ratios = await fmp(client, "/ratios-ttm", {"symbol": ticker})
        r0 = ratios[0] if isinstance(ratios, list) and ratios else (ratios if isinstance(ratios, dict) else {})
        ev_ebitda_ttm = r0.get("enterpriseValueMultipleTTM") or r0.get("evToEbitdaTTM")
    except Exception:
        pass

    data = {
        "price": price,
        "revenue": revenue,
        "avg_margin": avg_margin,
        "hist_cagr": hist_cagr,
        "shares": shares,
        "net_debt": net_debt,
        "ev_ebitda_ttm": ev_ebitda_ttm,
        "history": income_list,
    }

    set_cache(ticker, data)
    return data


# ---------------------------------------------------------------------------
# Pydantic modely pro /valuation
# ---------------------------------------------------------------------------

class ScenarioParams(BaseModel):
    revenue_cagr: float
    ebitda_margin: float
    ev_ebitda_multiple: float

class ValuationRequest(BaseModel):
    required_return: float = 0.12   # požadovaný roční výnos, default 12 %
    years: int = 2                  # horizont projekce, default 2 roky
    bear: ScenarioParams | None = None
    base: ScenarioParams | None = None
    bull: ScenarioParams | None = None


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok", "api_key_set": bool(API_KEY)}


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

@app.get("/search")
async def search(query: str):
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            data = await fmp(client, "/search-symbol", {"query": query, "limit": 8})
            if not data:
                data = await fmp(client, "/search-name", {"query": query, "limit": 8})
            return data if isinstance(data, list) else []
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=502, detail=str(e))


# ---------------------------------------------------------------------------
# Company detail (profile + financials + estimates + ratios)
# ---------------------------------------------------------------------------

@app.get("/company/{ticker}")
async def company(ticker: str):
    ticker = ticker.upper()
    async with httpx.AsyncClient(timeout=20) as client:
        try:
            profile, income = await asyncio.gather(
                fmp(client, "/profile", {"symbol": ticker}),
                fmp(client, "/income-statement", {"symbol": ticker, "limit": 4}),
            )

            prof = profile[0] if isinstance(profile, list) and profile else {}
            inc0 = income[0] if isinstance(income, list) and income else {}

            print("\n--- DEBUG ---")
            print("Ticker:", ticker)
            print("PROFILE:", prof)
            print("INCOME:", inc0)
            print("SHARES profile:", prof.get("sharesOutstanding"))
            print("SHARES income:", inc0.get("weightedAverageShsOut"))
            print("----------------\n")


# ------------------------------------
# Debug
# ------------------------------------

            estimates: list = []
            ratios: dict = {}
            try:
                estimates = await fmp(client, "/analyst-estimates", {"symbol": ticker, "limit": 2})
            except Exception:
                pass
            try:
                r = await fmp(client, "/ratios-ttm", {"symbol": ticker})
                ratios = r[0] if isinstance(r, list) and r else (r if isinstance(r, dict) else {})
            except Exception:
                pass

            prof = (
                profile[0]
                if isinstance(profile, list) and profile
                else (profile if isinstance(profile, dict) else {})
            )
            if not prof or not prof.get("symbol"):
                raise HTTPException(status_code=404, detail="Firma nenalezena")

            return {
                "profile": prof,
                "income": income if isinstance(income, list) else [],
                "estimates": estimates if isinstance(estimates, list) else [],
                "ratios": ratios,
            }

        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=502, detail=str(e))


# ---------------------------------------------------------------------------
# Valuation — tříscénářový model
# ---------------------------------------------------------------------------

@app.post("/valuation/{ticker}")
async def valuation(ticker: str, body: ValuationRequest):
    """
    Tříscénářová (bear / base / bull) exit-multiple valuace.

    Pokud body neobsahuje parametry scénářů, backend je odvodí
    z historických dat (hist_cagr ± offset, avg_margin, ev_ebitda_ttm).

    Parametry v body:
      required_return  – požadovaný roční výnos (default 0.12 = 12 %)
      years            – horizont projekce (default 2)
      bear / base / bull:
        revenue_cagr      – roční růst tržeb pro scénář
        ebitda_margin     – EBITDA marže pro scénář
        ev_ebitda_multiple – EV/EBITDA exit multiple pro scénář
    """
    ticker = ticker.upper()
    async with httpx.AsyncClient(timeout=25) as client:
        try:
            d = await _fetch_valuation_data(client, ticker)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=502, detail=str(e))

    hist_cagr = d["hist_cagr"]
    avg_margin = d["avg_margin"]

    # EV/EBITDA multiple: z TTM dat, nebo fallback podle sektoru
    ev_m = d["ev_ebitda_ttm"] or 15.0
    # Ořežeme extrémní hodnoty (záporné nebo nereálné > 60)
    if not ev_m:
        if avg_margin < 0.1:
            ev_m = 8
        elif avg_margin < 0.2:
            ev_m = 12
        else:
            ev_m = 18

    # Výchozí scénáře odvozené z historie (lze přepsat v body)
    default_bear = ScenarioParams(
        revenue_cagr=max(hist_cagr - 0.08, -0.05),   # hist - 8 p.b., min -5 %
        ebitda_margin=max(avg_margin - 0.05, 0.01),   # marže -5 p.b.
        ev_ebitda_multiple=max(ev_m * 0.75, 5.0),     # multiple -25 %
    )
    default_base = ScenarioParams(
        revenue_cagr=hist_cagr,
        ebitda_margin=avg_margin,
        ev_ebitda_multiple=ev_m,
    )
    default_bull = ScenarioParams(
        revenue_cagr=hist_cagr + 0.06,               # hist + 6 p.b.
        ebitda_margin=min(avg_margin + 0.04, 0.60),  # marže +4 p.b.
        ev_ebitda_multiple=min(ev_m * 1.25, 60.0),  # multiple +25 %
    )

    bear_p = body.bear or default_bear
    base_p = body.base or default_base
    bull_p = body.bull or default_bull

    result = compute_scenarios(
        revenue=d["revenue"],
        net_debt=d["net_debt"],
        shares=d["shares"],
        price=d["price"],
        bear=bear_p.model_dump(),
        base=base_p.model_dump(),
        bull=bull_p.model_dump(),
        required_return=body.required_return,
        years=body.years,
    )
    result["ticker"] = ticker

    # Přidej historická data pro kontext
    result["historical"] = {
        "revenue": d["revenue"],
        "hist_cagr": round(d["hist_cagr"], 4),
        "avg_ebitda_margin": round(d["avg_margin"], 4),
        "ev_ebitda_ttm": round(d["ev_ebitda_ttm"], 1) if d["ev_ebitda_ttm"] else None,
        "net_debt": round(d["net_debt"], 0),
        "shares": round(d["shares"], 0),
    }

    return result


# ---------------------------------------------------------------------------
# Screener — batch valuace (base scénář)
# ---------------------------------------------------------------------------

@app.post("/screener")
async def screener(data: dict):
    """
    Body: { "tickers": ["AAPL", "MSFT", ...], "required_return": 0.12, "years": 2 }
    Vrátí tickers seřazené podle base upside sestupně.
    """
    tickers: list[str] = [t.upper() for t in data.get("tickers", [])]
    required_return: float = float(data.get("required_return", 0.12))
    years: int = int(data.get("years", 2))

    if not tickers:
        raise HTTPException(status_code=400, detail="Zadej aspoň jeden ticker")

    results = []
    async with httpx.AsyncClient(timeout=30) as client:
        async def process(ticker: str):
            try:
                d = await _fetch_valuation_data(client, ticker)
                hist_cagr = d["hist_cagr"]
                avg_margin = d["avg_margin"]
                ev_m = d["ev_ebitda_ttm"] or 15.0
                if not (3.0 <= ev_m <= 60.0):
                    ev_m = 15.0

                base = ScenarioParams(
                    revenue_cagr=hist_cagr,
                    ebitda_margin=avg_margin,
                    ev_ebitda_multiple=ev_m,
                )
                r = compute_scenarios(
                    revenue=d["revenue"],
                    net_debt=d["net_debt"],
                    shares=d["shares"],
                    price=d["price"],
                    bear=ScenarioParams(
                        revenue_cagr=max(hist_cagr - 0.08, -0.05),
                        ebitda_margin=max(avg_margin - 0.05, 0.01),
                        ev_ebitda_multiple=max(ev_m * 0.75, 5.0),
                    ).model_dump(),
                    base=base.model_dump(),
                    bull=ScenarioParams(
                        revenue_cagr=hist_cagr + 0.06,
                        ebitda_margin=min(avg_margin + 0.04, 0.60),
                        ev_ebitda_multiple=min(ev_m * 1.25, 60.0),
                    ).model_dump(),
                    required_return=required_return,
                    years=years,
                )
                r["ticker"] = ticker
                results.append(r)
            except Exception:
                pass

        await asyncio.gather(*[process(t) for t in tickers])

    results.sort(key=lambda x: x["scenarios"]["base"]["upside"], reverse=True)
    return results


# ---------------------------------------------------------------------------
# Sector performance
# ---------------------------------------------------------------------------

@app.get("/sector")
async def sector():
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            data = await fmp(client, "/sector-performance")
            return data
        except Exception as e:
            raise HTTPException(status_code=502, detail=str(e))


# ---------------------------------------------------------------------------
# Debug
# ---------------------------------------------------------------------------

@app.get("/debug/{ticker}")
async def debug(ticker: str):
    ticker = ticker.upper()
    async with httpx.AsyncClient(timeout=20) as client:
        try:
            profile = await fmp(client, "/profile", {"symbol": ticker})
            income = await fmp(client, "/income-statement", {"symbol": ticker, "limit": 1})
            prof = profile[0] if isinstance(profile, list) and profile else profile
            inc = income[0] if isinstance(income, list) and income else income
            return {"profile": prof, "income": inc}
        except Exception as e:
            return {"error": str(e)}
