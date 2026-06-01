import asyncio
import os
import time
import math
import httpx

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

from backend.sec import (
    get_cik_map,
    get_company_facts,
    extract_fundamentals,
)

from backend.technical import compute_technical
from backend.metrics import compute_metrics
from backend.storage import save_snapshot
from backend.valuation.model import run_scenarios

load_dotenv()

app = FastAPI(title="StockLens API (SEC-only)")

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

sem = asyncio.Semaphore(10)

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
# SAFE HTTP
# =========================================================

async def safe_get(client: httpx.AsyncClient, url: str, params: dict = None):
    try:
        r = await client.get(url, params=params, timeout=20)
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None


# =========================================================
# DATA PROVIDERS
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
# SEC LAYER
# =========================================================

_cik_map_cache = None


def get_cik(ticker: str):
    global _cik_map_cache
    if _cik_map_cache is None:
        _cik_map_cache = get_cik_map()
    return _cik_map_cache.get(ticker.upper())


async def get_sec_fundamentals(ticker: str):
    cik = get_cik(ticker)
    if not cik:
        return None

    data = get_company_facts(cik)
    if not data:
        return None

    return extract_fundamentals(data)


# =========================================================
# MERGE ENGINE (SEC SAFE)
# =========================================================

PRIORITY = {"twelvedata": 2, "sec": 1}


def merge(*sources):
    out = {}
    score = {}

    for s in sources:
        if not s:
            continue

        src = s.get("source", "unknown")
        conf = s.get("confidence", 0.5)
        sscore = PRIORITY.get(src, 0) + conf

        for k, v in s.items():
            if k in ("source", "confidence") or v is None:
                continue

            if k == "history":
                out.setdefault("history", {})
                out["history"].update(v)
                continue

            if k not in out or sscore > score.get(k, 0):
                out[k] = v
                score[k] = sscore

    return out


# =========================================================
# CORE DATA PIPELINE
# =========================================================

async def get_stock_data(client, ticker: str):
    cached = get_cache(ticker)
    if cached:
        return cached

    td, sec = await asyncio.gather(
        twelvedata_ohlcv(client, ticker),
        get_sec_fundamentals(ticker),
    )

    ohlcv = None
    if td and "ohlcv" in td:
        ohlcv = td.pop("ohlcv")

    merged = merge(td, sec)

    merged["ticker"] = ticker
    merged.setdefault("price", None)
    merged.setdefault("shares", None)

    cash = merged.get("cash") or 0
    debt = merged.get("debt") or 0
    merged["net_debt"] = merged.get("net_debt") or (debt - cash)

    if ohlcv and merged.get("price"):
        try:
            merged["technical"] = compute_technical(ohlcv, merged["price"])
        except Exception:
            merged["technical"] = None
    else:
        merged["technical"] = None

    set_cache(ticker, merged)
    save_snapshot(merged)

    return merged


# =========================================================
# API SCHEMAS
# =========================================================

class ScenarioParams(BaseModel):
    revenue_cagr: float = 0.0
    ebitda_margin: float = 0.2
    ev_ebitda_multiple: float = 15.0


class ValuationRequest(BaseModel):
    base: ScenarioParams | None = None


# =========================================================
# ENDPOINTS
# =========================================================

@app.get("/health")
async def health():
    return {"ok": True}


@app.delete("/cache")
async def clear_cache():
    _cache.clear()
    return {"cleared": True}


@app.get("/company/{ticker}")
async def company(ticker: str):
    async with httpx.AsyncClient() as client:
        d = await get_stock_data(client, ticker.upper())

    metrics_input = {
        "price": d.get("price"),
        **d,
    }

    metrics = compute_metrics(metrics_input)

    return {
        "ticker": ticker.upper(),
        "price": d.get("price"),
        "fundamentals": d,
        "metrics": metrics,
        "technical": d.get("technical"),
    }


@app.post("/valuation/{ticker}")
async def valuation(ticker: str, body: ValuationRequest):
    async with httpx.AsyncClient() as client:
        d = await get_stock_data(client, ticker.upper())

    shares = d.get("shares")
    price = d.get("price")

    if not shares:
        raise HTTPException(422, "Missing shares data")
    if not price:
        raise HTTPException(422, "Missing price")

    base = body.base.model_dump() if body.base else {}

    input_data = {
        "revenue": d.get("revenue") or 0,
        "ebitda_margin": base.get("ebitda_margin") or d.get("ebitda_margin") or 0.2,
        "ev_ebitda_multiple": base.get("ev_ebitda_multiple") or 15.0,
        "net_debt": d.get("net_debt") or 0,
        "shares": shares,
    }

    result = run_scenarios(input_data)

    return {
        "ticker": ticker.upper(),
        "price": price,
        "valuation": result,
        "data": d,
    }


@app.post("/screener")
async def screener(data: dict):
    tickers = [t.upper() for t in data.get("tickers", [])]
    if not tickers:
        raise HTTPException(400, "No tickers")

    results = []

    async with httpx.AsyncClient() as client:

        async def process(t):
            async with sem:
                try:
                    d = await get_stock_data(client, t)

                    if not d.get("shares") or not d.get("price"):
                        return None

                    res = run_scenarios({
                        "revenue": d.get("revenue") or 0,
                        "ebitda_margin": d.get("ebitda_margin") or 0.2,
                        "ev_ebitda_multiple": 15.0,
                        "net_debt": d.get("net_debt") or 0,
                        "shares": d.get("shares"),
                    })

                    base = (res.get("base") or {}).get("price")
                    if not base:
                        return None

                    current = d.get("price")
                    upside = (base / current - 1) if current else None

                    return {
                        "ticker": t,
                        "price": current,
                        "upside": upside,
                        "valuation": res,
                    }

                except Exception:
                    return None

        out = await asyncio.gather(*(process(t) for t in tickers))

    results = [r for r in out if r]
    results.sort(key=lambda x: x["upside"], reverse=True)

    return results
