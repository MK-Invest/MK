import asyncio
import os
import time
import math
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

from backend.sec import get_cik_map, get_company_facts, extract_fundamentals
from backend.eu_tickers import load_eu_tickers
from backend.technical import compute_technical
from backend.metrics import compute_metrics
from backend.storage import save_snapshot
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

TD_API_KEY = os.getenv("TWELVEDATA_API_KEY", "")
CACHE_TTL = 300

_cache = {}
_sem = asyncio.Semaphore(10)

_sec_cache = None
_eu_cache = None

# =========================================================
# CACHE
# =========================================================

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
# HTTP
# =========================================================

async def safe_get(client: httpx.AsyncClient, url: str, params=None):
    try:
        r = await client.get(url, params=params, timeout=20)
        if r.status_code != 200:
            return None
        return r.json()
    except:
        return None

# =========================================================
# TICKERS
# =========================================================

def get_all_tickers():
    global _sec_cache, _eu_cache

    if _sec_cache is None:
        _sec_cache = get_cik_map()

    if _eu_cache is None:
        _eu_cache = load_eu_tickers()

    return _sec_cache, _eu_cache

# =========================================================
# TWELVEDATA
# =========================================================

async def twelvedata_ohlcv(client, ticker: str):
    if not TD_API_KEY:
        return None

    data = await safe_get(
        client,
        "https://api.twelvedata.com/time_series",
        params={
            "symbol": ticker,
            "interval": "1day",
            "outputsize": 200,
            "apikey": TD_API_KEY,
        },
    )

    if not data or "values" not in data:
        return None

    values = data["values"]
    price = float(values[0]["close"])

    return {
        "price": price,
        "ohlcv": values,
        "source": "twelvedata",
        "confidence": 0.5,
    }

# =========================================================
# SEC
# =========================================================

def get_sec_fundamentals(ticker: str):
    cik_map, _ = get_all_tickers()
    cik = cik_map.get(ticker.upper())
    if not cik:
        return None

    data = get_company_facts(cik)
    if not data:
        return None

    return extract_fundamentals(data)

# =========================================================
# MERGE
# =========================================================

PRIORITY = {"twelvedata": 2, "sec": 3, "fmp": 1, "eu": 2}

def merge(*sources):
    out = {}
    score = {}

    for s in sources:
        if not s:
            continue

        src = s.get("source", "unknown")
        conf = s.get("confidence", 0.5)

        for k, v in s.items():
            if k in ("source", "confidence") or v is None:
                continue

            sscore = PRIORITY.get(src, 0) + conf
            if k not in out or sscore > score[k]:
                out[k] = v
                score[k] = sscore

    return out

# =========================================================
# STOCK DATA CORE
# =========================================================

async def get_stock_data(client, ticker: str):
    cached = get_cache(ticker)
    if cached:
        return cached

    td, sec = await asyncio.gather(
        twelvedata_ohlcv(client, ticker),
        asyncio.to_thread(get_sec_fundamentals, ticker),
    )

    merged = merge(td, sec)

    merged["ticker"] = ticker
    merged.setdefault("price", None)
    merged.setdefault("revenue", 0)
    merged.setdefault("shares", None)

    if td and sec:
        try:
            merged["technical"] = compute_technical(td["ohlcv"], merged["price"])
        except:
            merged["technical"] = None

    set_cache(ticker, merged)
    save_snapshot(merged)

    return merged

# =========================================================
# SEARCH (US + EU)
# =========================================================

@app.get("/search")
async def search(query: str):
    q = query.upper().strip()

    sec, eu = get_all_tickers()

    results = []

    # US (SEC)
    for t in sec:
        if q in t:
            results.append({
                "symbol": t,
                "name": t,
                "region": "US"
            })

    # EU
    for t, meta in eu.items():
        if q in t or q in (meta.get("name") or "").upper():
            results.append({
                "symbol": t,
                "name": meta.get("name"),
                "exchange": meta.get("exchange"),
                "region": "EU"
            })

    return results[:20]

# =========================================================
# COMPANY
# =========================================================

@app.get("/company/{ticker}")
async def company(ticker: str):
    async with httpx.AsyncClient() as client:
        d = await get_stock_data(client, ticker.upper())

    metrics = compute_metrics(d)

    return {
        "ticker": ticker.upper(),
        "price": d.get("price"),
        "fundamentals": d,
        "metrics": metrics,
        "technical": d.get("technical"),
    }

# =========================================================
# VALUATION
# =========================================================

class ScenarioParams(BaseModel):
    revenue_cagr: float
    ebitda_margin: float
    ev_ebitda_multiple: float

class ValuationRequest(BaseModel):
    required_return: float = 0.12
    years: int = 2
    base: ScenarioParams | None = None

@app.post("/valuation/{ticker}")
async def valuation(ticker: str, body: ValuationRequest):
    async with httpx.AsyncClient() as client:
        d = await get_stock_data(client, ticker.upper())

    if not d.get("price"):
        raise HTTPException(422, "No price data")

    shares = d.get("shares") or 1

    base_override = body.base.model_dump() if body.base else {}

    input_data = {
        "revenue": d.get("revenue") or 0,
        "ebitda_margin": base_override.get("ebitda_margin") or 0.2,
        "ev_ebitda_multiple": base_override.get("ev_ebitda_multiple") or 15,
        "net_debt": d.get("net_debt") or 0,
        "shares": shares,
    }

    result = run_scenarios(input_data)

    return {
        "ticker": ticker.upper(),
        "price": d.get("price"),
        "valuation": result,
    }

# =========================================================
# HEALTH
# =========================================================

@app.get("/health")
async def health():
    return {
        "ok": True,
        "twelvedata": bool(TD_API_KEY),
    }
