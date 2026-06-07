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
        params={"symbol": ticker, "interval": "1day", "outputsize": 200, "apikey": TD_API_KEY},
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
    out:   dict = {}
    score: dict = {}
    for s in sources:
        if not s:
            continue
        src  = s.get("source", "unknown")
        conf = s.get("confidence", 0.5)
        for k, v in s.items():
            if k in ("source", "confidence") or v is None:
                continue
            sscore = PRIORITY.get(src, 0) + conf
            if k not in out or sscore > score[k]:
                out[k]   = v
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
    return _cik_map_cache.get(ticker.upper())


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
    revenue_cagr:       float
    ebitda_margin:      float
    ev_ebitda_multiple: float


class ValuationRequest(BaseModel):
    required_return: float = 0.12
    years: int = 2
    base: ScenarioParams | None = None


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
    """
    Vrátí fundamentals, metriky a technickou analýzu.
    Auto-detekuje US (SEC) vs EU (yfinance).
    """
    ticker = ticker.upper()
    async with httpx.AsyncClient() as client:
        d = await get_stock_data(client, ticker)

    fundamentals = {k: v for k, v in d.items() if k not in ("ticker", "technical", "_history", "ohlcv")}

    history = d.get("_history")
    if history:
        fundamentals["history"] = history

    # Přidej název firmy pokud je dostupný (EU z yfinance)
    if "name" not in fundamentals:
        fundamentals["name"] = ticker

    metrics_input = {**fundamentals, "price": d.get("price")}
    metrics = compute_metrics(metrics_input)

    return {
        "ticker":       ticker,
        "name":         fundamentals.get("name", ticker),
        "price":        d.get("price"),
        "fundamentals": fundamentals,
        "metrics":      metrics,
        "technical":    d.get("technical"),
    }


@app.post("/valuation/{ticker}")
async def valuation(ticker: str, body: ValuationRequest):
    ticker = ticker.upper()
    async with httpx.AsyncClient() as client:
        d = await get_stock_data(client, ticker)

    shares = d.get("shares")
    if not shares or shares == 0:
        raise HTTPException(status_code=422, detail=f"Chybí data o počtu akcií pro {ticker}")

    price = d.get("price")
    if not price:
        raise HTTPException(status_code=422, detail=f"Cena nedostupná pro {ticker}")

    base_override = body.base.model_dump() if body.base else {}
    sec_margin    = d.get("ebitda_margin")

    input_data = {
        "revenue":            d.get("revenue") or 0,
        "ebitda_margin":      base_override.get("ebitda_margin") or sec_margin or 0.20,
        "ev_ebitda_multiple": base_override.get("ev_ebitda_multiple") or 15.0,
        "net_debt":           d.get("net_debt") or 0,
        "shares":             shares,
    }
    result = run_scenarios(input_data)

    return {"ticker": ticker, "price": price, "data": d, "valuation": result}

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
