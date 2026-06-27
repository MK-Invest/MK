import asyncio
import os
import time
import math
import httpx
from backend.technical import compute_technical
from backend.metrics import compute_metrics
from backend.storage import save_snapshot
from backend.eu import get_eu_fundamentals, is_us_ticker
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from backend.sec import get_cik_map, get_company_facts, extract_fundamentals
from backend.valuation.model import run_scenarios

load_dotenv()

app = FastAPI(title="StockLens API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================================================
# CONFIG
# =========================================================

FMP_STABLE  = "https://financialmodelingprep.com/stable"
FMP_API_KEY = os.getenv("FMP_API_KEY", "")
TD_API_KEY  = os.getenv("TWELVEDATA_API_KEY", "")

CACHE_TTL = 300
_cache: dict = {}

lock = asyncio.Lock()
sem  = asyncio.Semaphore(10)

# =========================================================
# UTIL
# =========================================================

def safe_float(x):
    try:
        if x is None:
            return None
        if isinstance(x, str):
            x = x.replace(",", "")
        v = float(x)
        if math.isnan(v) or math.isinf(v):
            return None
        return v
    except Exception:
        return None


def get_cache(key: str):
    v = _cache.get(key)
    if not v:
        return None
    if time.time() - v["time"] > CACHE_TTL:
        _cache.pop(key, None)
        return None
    return v["data"]


def set_cache(key: str, data):
    _cache[key] = {"data": data, "time": time.time()}


# =========================================================
# SAFE HTTP
# =========================================================

async def safe_get(client: httpx.AsyncClient, url: str, params: dict = None):
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            ),
            "Accept": "application/json",
            "Connection": "keep-alive",
        }
        r = await client.get(
            url, params=params, headers=headers,
            timeout=20, follow_redirects=True,
        )
        if r.status_code != 200:
            print(f"[safe_get] {url} → HTTP {r.status_code}: {r.text[:300]}")
            return None
        return r.json()
    except Exception as e:
        print(f"[safe_get] ERROR {url}: {repr(e)}")
        return None


# =========================================================
# PROVIDERS — US pipeline
# =========================================================

async def twelvedata_ohlcv(client, ticker: str) -> dict | None:
    """Cena + OHLCV z TwelveData — pouze pro US tickery."""
    if not TD_API_KEY:
        return None

    data = await safe_get(
        client,
        "https://api.twelvedata.com/time_series",
        params={"symbol": ticker, "interval": "1day", "outputsize": 1300, "apikey": TD_API_KEY},
    )
    if not data or "values" not in data:
        return None

    values = data.get("values", [])
    if not values:
        return None

    price = safe_float(values[0].get("close"))
    if not price:
        return None

    return {"price": price, "ohlcv": values, "source": "twelvedata", "confidence": 0.5}


async def fmp_fundamentals_us(client: httpx.AsyncClient, ticker: str) -> dict | None:
    """FMP záloha fundamentals pro US akcie."""
    if not FMP_API_KEY:
        return None
    try:
        income, balance = await asyncio.gather(
            safe_get(client, f"{FMP_STABLE}/income-statement",
                     params={"symbol": ticker, "limit": 1, "apikey": FMP_API_KEY}),
            safe_get(client, f"{FMP_STABLE}/balance-sheet-statement",
                     params={"symbol": ticker, "limit": 1, "apikey": FMP_API_KEY}),
        )
        inc  = (income  or [{}])[0]
        bal  = (balance or [{}])[0]
        debt = safe_float(bal.get("totalDebt")) or 0
        cash = safe_float(bal.get("cashAndCashEquivalents")) or 0
        return {
            "revenue":  safe_float(inc.get("revenue")),
            "ebitda":   safe_float(inc.get("ebitda")),
            "net_debt": debt - cash,
            "source":   "fmp",
            "confidence": 0.6,
        }
    except Exception as e:
        print(f"[fmp_us] ERROR {ticker}: {repr(e)}")
        return None


async def get_sec_fundamentals(ticker: str) -> dict | None:
    cik = get_cik(ticker)
    if not cik:
        return None
    data = get_company_facts(cik)
    if not data:
        return None
    result = extract_fundamentals(data)
    print(f"[sec] {ticker} revenue={result.get('revenue')} ni={result.get('net_income')}")
    return result


# =========================================================
# MERGE ENGINE
# =========================================================

PRIORITY = {"yfinance": 4, "fmp": 3, "sec": 2, "twelvedata": 1}

def merge(*sources) -> dict:
    out = {}
    score = {}
 
    for s in sources:
        if not s:
            continue
 
        src = s.get("source", "unknown")
        conf = s.get("confidence", 0.5)
        base_score = PRIORITY.get(src, 0) + conf
 
        for k, v in s.items():
            if k in ("source", "confidence"):
                continue
 
            # SPECIÁLNÍ FIX: historie nikdy nepřepisuj
            if k == "history":
                out.setdefault("history", v)
                continue
 
            # KLÍČOVÝ FIX: None hodnota nesmí přepsat existující platná data,
            # bez ohledu na prioritu zdroje. Bez tohoto fixu vyšší-prioritní
            # zdroj s chybějícími daty (např. FMP bez API klíče nebo bez
            # pokrytí pro daný ticker) tiše smaže platná data z nižší-
            # prioritního zdroje (např. SEC), což shodí celý valuation model.
            if v is None:
                continue
 
            sscore = base_score
 
            if k not in out or sscore > score.get(k, -1):
                out[k] = v
                score[k] = sscore
 
    return out


# =========================================================
# CORE DATA LAYER
# =========================================================

_cik_map_cache: dict | None = None


def get_cik(ticker: str) -> str | None:
    global _cik_map_cache
    
    if _cik_map_cache is None:
        _cik_map_cache = get_cik_map()
    item = _cik_map_cache.get(ticker.upper())

    if not item:
        return None
    
    return item["cik"]

def get_company_name(ticker: str) -> str:
    global _cik_map_cache

    if _cik_map_cache is None:
        _cik_map_cache = get_cik_map()

    item = _cik_map_cache.get(ticker.upper())

    if not item:
        return ticker

    return item["name"]


async def get_stock_data(client, ticker: str) -> dict:
    """
    Auto-detekuje US vs EU a routuje do správného pipeline.

    US (bez tečky, CIK v SEC):  TwelveData + SEC + FMP záloha
    EU (s tečkou nebo bez CIK): yfinance (cena + OHLCV + fundamentals)
    """
    cached = get_cache(ticker)
    if cached:
        return cached

    global _cik_map_cache
    if _cik_map_cache is None:
        _cik_map_cache = get_cik_map()

    us = is_us_ticker(ticker, _cik_map_cache)
    print(f"[pipeline] {ticker} → {'US (SEC)' if us else 'EU (yfinance)'}")

    ohlcv   = None
    history = None

    if us:
        # ── US pipeline ──────────────────────────────────
        td, sec, fmp_fund = await asyncio.gather(
            twelvedata_ohlcv(client, ticker),
            get_sec_fundamentals(ticker),
            fmp_fundamentals_us(client, ticker),
        )
        if td and "ohlcv" in td:
            ohlcv = td.pop("ohlcv")
        merged  = merge(td, sec, fmp_fund)
        history = (sec or {}).get("history")

    else:
        # ── EU pipeline — yfinance obstará vše ───────────
        eu = await get_eu_fundamentals(ticker)
        if eu and "ohlcv" in eu:
            ohlcv = eu.pop("ohlcv")
        merged  = merge(eu)
        history = (eu or {}).get("history")

    # ── Společné post-processing ─────────────────────────
    cash = merged.get("cash") or 0
    debt = merged.get("debt") or 0
    if "net_debt" not in merged:
        merged["net_debt"] = debt - cash

    merged["ticker"] = ticker
    merged.setdefault("price", None)
    merged.setdefault("revenue", 0)
    merged.setdefault("shares", None)

    if history:
        merged["_history"] = history

    # Technická analýza (cena + OHLCV nutné)
    if ohlcv and merged.get("price"):
        try:
            merged["technical"] = compute_technical(ohlcv, merged["price"])
        except Exception as e:
            print(f"[technical] {ticker} error: {repr(e)}")
            merged["technical"] = None
    else:
        merged["technical"] = None

    print(f"[stock_data] {ticker} | price={merged.get('price')} | revenue={merged.get('revenue')}")

    set_cache(ticker, merged)
    save_snapshot(merged)
    return merged


# =========================================================
# SEARCH HELPER — TwelveData symbol search
# =========================================================

async def td_symbol_search(query: str) -> list[dict]:
    """
    Vyhledá tickery přes TwelveData /symbol_search.
    Vrátí [{symbol, name, exchange, market}, ...].
    Funguje pro US i EU, vrací název firmy.
    """
    if not TD_API_KEY:
        return []
    try:
        async with httpx.AsyncClient() as client:
            data = await safe_get(
                client,
                "https://api.twelvedata.com/symbol_search",
                params={"symbol": query, "outputsize": 8, "apikey": TD_API_KEY},
            )
        if not data or "data" not in data:
            return []
        results = []
        for item in data["data"]:
            results.append({
                "symbol":   item.get("symbol", ""),
                "name":     item.get("instrument_name", item.get("symbol", "")),
                "exchange": item.get("exchange", ""),
                "market":   item.get("country", ""),
                "type":     item.get("instrument_type", ""),
            })
        return results
    except Exception as e:
        print(f"[td_search] error: {repr(e)}")
        return []


# =========================================================
# SCHEMAS
# =========================================================

class ScenarioParams(BaseModel):
    revenue_cagr: float | None = None
    ebitda_margin: float | None = None
    ev_ebitda_multiple: float | None = None
    fcf_margin: float | None = None
    exit_multiple: float | None = None


class ValuationRequest(BaseModel):
    required_return: float = 0.10
    years: int = 3
    bear: ScenarioParams | None = None
    base: ScenarioParams | None = None
    bull: ScenarioParams | None = None


# =========================================================
# ENDPOINTS
# =========================================================

@app.get("/health")
async def health():
    return {"ok": True, "fmp": bool(FMP_API_KEY), "twelvedata": bool(TD_API_KEY)}


@app.delete("/cache")
async def clear_cache():
    count = len(_cache)
    _cache.clear()
    return {"cleared": count}


@app.delete("/cache/{ticker}")
async def clear_cache_ticker(ticker: str):
    ticker = ticker.upper()
    existed = ticker in _cache
    _cache.pop(ticker, None)
    return {"ticker": ticker, "cleared": existed}


@app.get("/search")
async def search(query: str):
    """
    Kombinované vyhledávání:
    1. TwelveData symbol_search → výsledky s názvem firmy, burzou (US + EU)
    2. SEC CIK mapa → doplnění US tickerů pokud TD nic nenajde

    Podporuje vyhledávání podle tickeru i názvu firmy.
    """
    if not query or len(query) < 1:
        return []

    q = query.strip()

    # TwelveData symbol search (název firmy + ticker + burza)
    td_results = await td_symbol_search(q)

    if td_results:
        return td_results[:8]

    # Fallback: SEC CIK mapa (pouze US, jen ticker)
    global _cik_map_cache
    if _cik_map_cache is None:
        _cik_map_cache = get_cik_map()

    q_up    = q.upper()
    exact   = []
    partial = []

    for ticker in _cik_map_cache:
        if ticker == q_up:
            exact.append({"symbol": ticker, "name": ticker, "exchange": "US", "market": "United States"})
        elif q_up in ticker:
            partial.append({"symbol": ticker, "name": ticker, "exchange": "US", "market": "United States"})

    return (exact + partial)[:8]


@app.get("/company/{ticker}")
async def company(ticker: str):
    ticker = ticker.upper()

    try:
        async with httpx.AsyncClient() as client:
            d = await get_stock_data(client, ticker)

        if not d:
            raise HTTPException(status_code=404, detail="No data returned")

        fundamentals = {
            k: v for k, v in d.items()
            if k not in ("ticker", "technical", "_history", "ohlcv")
        }

        history = (
            d.get("_history")
            or d.get("history")
            or {}
        )

        # HARD FIX: normalizace struktury
        history.setdefault("revenue", [])
        history.setdefault("net_income", [])
        history.setdefault("operating_income", [])
        history.setdefault("depreciation", [])

        fundamentals["history"] = history

        if "name" not in fundamentals:
            fundamentals["name"] = get_company_name(ticker)

        metrics_input = {
            "price": d.get("price"),
            "shares": fundamentals.get("shares"),
            "equity": fundamentals.get("equity"),
            "debt": fundamentals.get("debt") or 0,
            "cash": fundamentals.get("cash") or 0,
            "fcf": fundamentals.get("fcf"),
            "roic": fundamentals.get("roic"),
            "nopat": fundamentals.get("nopat"),
            "net_debt": fundamentals.get("net_debt"),
            "tax_rate": fundamentals.get("tax_rate"),
            "roe": fundamentals.get("roe"),
            "roa": fundamentals.get("roa"),
            "current_ratio": fundamentals.get("current_ratio"),
            "dps": fundamentals.get("dps"),
            "total_assets": fundamentals.get("total_assets"),
            "eps_quarterly": fundamentals.get("eps_quarterly") or [],
            "volume": fundamentals.get("volume"),
            "history": fundamentals["history"],
            "revenue": fundamentals.get("revenue"),
            "net_income": fundamentals.get("net_income"),
            "ebitda": fundamentals.get("ebitda"),
        }

        print(f"[DEBUG] shares={fundamentals.get('shares')}")
        print(f"[DEBUG] revenue={fundamentals.get('revenue')}")
        print(f"[DEBUG] net_income={fundamentals.get('net_income')}")
        print(f"[DEBUG] ebitda={fundamentals.get('ebitda')}")
        print(f"[DEBUG] history_keys={list(history.keys())}")

        metrics = compute_metrics(metrics_input)

        print(f"[DEBUG] metrics_ttm={metrics.get('ttm')}")

        return {
            "ticker": ticker,
            "name": fundamentals.get("name"),
            "price": d.get("price"),
            "fundamentals": fundamentals,
            "metrics": metrics,
            "technical": d.get("technical"),
        }

    except Exception as e:
        print(f"[company ERROR] {ticker}: {repr(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/valuation/{ticker}")
async def valuation(ticker: str, body: ValuationRequest):
    ticker = ticker.upper()
    async with httpx.AsyncClient() as client:
        d = await get_stock_data(client, ticker)

    shares = d.get("shares")
    if not shares or shares == 0:
        raise HTTPException(status_code=422, detail=f"Chybi data o poctu akcii pro {ticker}")

    price = d.get("price")
    if not price:
        raise HTTPException(status_code=422, detail=f"Cena nedostupna pro {ticker}")

    base_override = body.base.model_dump(exclude_none=True) if body.base else {}
    sec_margin = d.get("ebitda_margin")
    revenue = d.get("revenue") or 0
    net_debt = d.get("net_debt") or 0

    fcf = d.get("fcf")
    revenue = d.get("revenue") or 0
    net_debt = d.get("net_debt") or 0

    # ── Odvoď vstupy z reálných dat ─────────────────────────────────
    ebitda     = d.get("ebitda")
    net_income = d.get("net_income")

    # EBITDA margin z dat, ne hard-coded default
    if sec_margin and sec_margin > 0:
        derived_margin = sec_margin
    elif ebitda and revenue:
        derived_margin = ebitda / revenue
    elif net_income and revenue:
        derived_margin = (net_income / revenue) * 1.4
    else:
        derived_margin = 0.20

    # EV/EBITDA multiple z TTM metrik
    ttm_for_multiple = compute_metrics({**d, "history": d.get("_history") or d.get("history") or {}})
    ttm_ev_ebitda = (ttm_for_multiple.get("ttm") or {}).get("ev_ebitda")
    if ttm_ev_ebitda and 5 < ttm_ev_ebitda < 80:
        derived_multiple = round(ttm_ev_ebitda, 1)
    else:
        derived_multiple = 20.0

    # Revenue growth z historických dat — 3-letý CAGR (12 kvartálů)
    # YoY je příliš volatilní, 3Y CAGR lépe vystihuje strukturální trend
    rev_hist_raw = (d.get("_history") or d.get("history") or {}).get("revenue") or []
    derived_growth = d.get("revenue_growth")
    if not derived_growth:
        if len(rev_hist_raw) >= 13:
            # 3-letý CAGR: nejnovější vs stejný kvartál před 3 lety
            newest_val = rev_hist_raw[0].get("val")
            oldest_val = rev_hist_raw[12].get("val")
            if newest_val and oldest_val and oldest_val > 0:
                derived_growth = (newest_val / oldest_val) ** (1/3) - 1
        elif len(rev_hist_raw) >= 5:
            # 1-letý CAGR jako fallback
            newest_val = rev_hist_raw[0].get("val")
            oldest_val = rev_hist_raw[4].get("val")
            if newest_val and oldest_val and oldest_val > 0:
                derived_growth = (newest_val / oldest_val) - 1
    if not derived_growth:
        derived_growth = 0.05

    input_data = {
        "revenue":           revenue,
        "ebitda_margin":     base_override.get("ebitda_margin") or derived_margin,
        "ev_ebitda_multiple": base_override.get("ev_ebitda_multiple") or derived_multiple,
        "net_debt":          net_debt,
        "shares":            shares,
        "fcf":               fcf,
        "fcf_3y_median": d.get("fcf_3y_median"),   # ← nové
        "nopat":             d.get("nopat"),
        "roic":              d.get("roic"),
        "cfo": d.get("cfo"),
        "price":      price,                    # ← nové, pro P/E a P/FCF multiple výpočet
        "net_income": d.get("net_income"),
        "revenue_growth":    base_override.get("revenue_cagr") or derived_growth,
        "revenue_cagr_5y":    d.get("revenue_cagr_5y"),
        "net_income_cagr_5y": d.get("net_income_cagr_5y"),
        "tax_rate":          d.get("tax_rate"),
        "fcf_margin":        (fcf / revenue) if (revenue and fcf is not None) else None,
    }

    overrides = {
        name: sc.model_dump(exclude_none=True)
        for name, sc in {"bear": body.bear, "base": body.base, "bull": body.bull}.items()
        if sc is not None
    }

    raw = run_scenarios(
        input_data,
        wacc=body.required_return,
        years=body.years,
        scenario_overrides=overrides,
    )

    scenarios = {}
    for name, sc in raw.items():
        intrinsic = sc.get("price")
        upside = (intrinsic / price - 1) if intrinsic is not None and price else None
        exit_px = sc.get("exit_price_per_share") or 0
        if price and body.years and exit_px > 0:
            required_cagr = (exit_px / price) ** (1 / body.years) - 1
        else:
            required_cagr = None
        scenarios[name] = {
            **sc,
            "intrinsic_value": intrinsic,
            "upside": upside,
            "required_cagr": required_cagr,
        }

    metrics = compute_metrics({**d, "history": d.get("_history") or d.get("history") or {}})
    ttm = metrics.get("ttm", {}) if metrics else {}
    hist = d.get("_history") or d.get("history") or {}
    rev_hist = hist.get("revenue") or []

    hist_cagr = None
    if len(rev_hist) >= 2:
        newest = rev_hist[0].get("val")
        oldest = rev_hist[-1].get("val")
        periods = max(len(rev_hist) - 1, 1)
        if newest and oldest and oldest > 0:
            hist_cagr = (newest / oldest) ** (1 / periods) - 1

    margins = []
    for op, dep, rev in zip(hist.get("operating_income") or [], hist.get("depreciation") or [], rev_hist):
        rev_val = rev.get("val")
        if rev_val:
            margins.append(((op.get("val") or 0) + (dep.get("val") or 0)) / rev_val)

    historical = {
        "hist_cagr": hist_cagr,
        "avg_ebitda_margin": sum(margins) / len(margins) if margins else sec_margin,
        "ev_ebitda_ttm": round(ttm.get("ev_ebitda"), 2) if ttm.get("ev_ebitda") is not None else None,
        "net_debt": net_debt,
        "shares": shares,
    }

    base_upside = scenarios.get("base", {}).get("upside")
    if base_upside is None:
        rating, rating_color = "N/A", "neutral"
    elif base_upside >= 0.25:
        rating, rating_color = "BUY", "green"
    elif base_upside >= -0.10:
        rating, rating_color = "HOLD", "amber"
    else:
        rating, rating_color = "SELL", "red"

    return {
        "ticker": ticker,
        "price": price,
        "required_return": body.required_return,
        "years": body.years,
        "scenarios": scenarios,
        "historical": historical,
        "rating": rating,
        "rating_color": rating_color,
        "valuation": raw,
        "data": d,
    }

@app.get("/debug-eu/{ticker}")
async def debug_eu(ticker: str):
    from backend.eu import _fetch_yfinance
    result = _fetch_yfinance(ticker)
    if not result:
        return {"error": "yfinance vrátil None"}
    return {
        "price":    result.get("price"),
        "revenue":  result.get("revenue"),
        "name":     result.get("name"),
        "ohlcv_count": len(result.get("ohlcv", [])),
        "history_revenue": result.get("history", {}).get("revenue", [])[:3],
    }

@app.get("/debug/{ticker}")
async def debug(ticker: str):
    ticker = ticker.upper()
    cik = get_cik(ticker)
    if not cik:
        return {"error": "CIK not found — EU ticker? Zkus /company/{ticker}"}

    data = get_company_facts(cik)
    if not data:
        return {"error": "No SEC data"}

    gaap = data["facts"].get("us-gaap", {})
    result = {}

    for c in ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"]:
        items  = gaap.get(c, {}).get("units", {}).get("USD", [])
        recent = [i for i in items if i.get("end", "") >= "2024-01-01"]
        recent.sort(key=lambda x: x.get("end", ""), reverse=True)
        result[c] = recent[:6]

    for c in ["DepreciationAndAmortization", "DepreciationDepletionAndAmortization",
              "DepreciationAmortizationAndAccretion", "Depreciation"]:
        items  = gaap.get(c, {}).get("units", {}).get("USD", [])
        recent = [i for i in items if i.get("end", "") >= "2023-01-01"]
        recent.sort(key=lambda x: x.get("end", ""), reverse=True)
        result[f"_dep_{c}"] = recent[:6]

    for c in ["NetIncomeLoss", "OperatingIncomeLoss"]:
        items  = gaap.get(c, {}).get("units", {}).get("USD", [])
        recent = [i for i in items if i.get("end", "") >= "2024-01-01"]
        recent.sort(key=lambda x: x.get("end", ""), reverse=True)
        result[f"_{c}"] = recent[:6]

    return result


@app.post("/screener")
async def screener(data: dict):
    tickers = [str(t).upper() for t in data.get("tickers", [])]
    if not tickers:
        raise HTTPException(status_code=400, detail="Zadej alespoň jeden ticker")

    async with httpx.AsyncClient() as client:
        async def process(ticker: str):
            async with sem:
                try:
                    d = await get_stock_data(client, ticker)
                    shares = d.get("shares")
                    if not shares or shares == 0:
                        return None
                    res = run_scenarios({
                        "revenue":            d.get("revenue") or 0,
                        "ebitda_margin":      d.get("ebitda_margin") or 0.20,
                        "ev_ebitda_multiple": 15.0,
                        "net_debt":           d.get("net_debt") or 0,
                        "shares":             shares,
                    })
                    base_price    = (res.get("base") or {}).get("price")
                    current_price = d.get("price") or 0
                    if not res or base_price is None or current_price == 0:
                        return None
                    return {
                        "ticker":    ticker,
                        "price":     current_price,
                        "upside":    base_price / current_price - 1,
                        "valuation": res,
                    }
                except Exception as e:
                    print(f"[screener] {ticker} error: {repr(e)}")
                    return None

        gathered = await asyncio.gather(*(process(t) for t in tickers))

    results = [r for r in gathered if r is not None]
    results.sort(key=lambda x: x["upside"], reverse=True)
    return results
