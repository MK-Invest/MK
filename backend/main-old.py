import asyncio
import os
import time
import math
import httpx
from backend.storage import save_snapshot
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
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

FMP_STABLE = "https://financialmodelingprep.com/stable"
FMP_API_KEY = os.getenv("FMP_API_KEY", "")
TD_API_KEY = os.getenv("TWELVEDATA_API_KEY", "")

CACHE_TTL = 300
_cache = {}

lock = asyncio.Lock()
sem = asyncio.Semaphore(10)

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
    except:
        return None


def get_cache(key):
    v = _cache.get(key)
    if not v:
        return None
    if time.time() - v["time"] > CACHE_TTL:
        _cache.pop(key, None)
        return None
    return v["data"]


def set_cache(key, data):
    _cache[key] = {"data": data, "time": time.time()}


# =========================================================
# SAFE HTTP
# =========================================================

async def safe_get(client, url, params=None):
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
            url,
            params=params,
            headers=headers,
            timeout=20,
            follow_redirects=True,
        )

        print("URL:", url)
        print("STATUS:", r.status_code)

        if r.status_code != 200:
            print("BODY:", r.text[:500])
            return None

        return r.json()

    except Exception as e:
        print("SAFE_GET ERROR:", repr(e))
        return None

# =========================================================
# PROVIDERS
# =========================================================

# -------------------------
# TWELVE DATA (PRICE FALLBACK)
# -------------------------

async def twelvedata_price(client, ticker):
    if not TD_API_KEY:
        return None

    data = await safe_get(
        client,
        "https://api.twelvedata.com/quote",
        params={"symbol": ticker, "apikey": TD_API_KEY},
    )

    if not data:
        return None

    return {
        "price": safe_float(data.get("close")),
        "source": "twelvedata",
        "confidence": 0.5,
    }

# -------------------------
# FMP (OPTIONAL ENRICHMENT ONLY)
# -------------------------

async def fmp_fundamentals(client, ticker):
    if not FMP_API_KEY:
        return None

    try:
        income = await safe_get(
            client,
            f"{FMP_STABLE}/income-statement",
            params={"symbol": ticker, "limit": 1, "apikey": FMP_API_KEY},
        )

        balance = await safe_get(
            client,
            f"{FMP_STABLE}/balance-sheet-statement",
            params={"symbol": ticker, "limit": 1, "apikey": FMP_API_KEY},
        )

        inc = (income or [{}])[0]
        bal = (balance or [{}])[0]
        debt = safe_float(bal.get("totalDebt")) or 0
        cash = safe_float(bal.get("cashAndCashEquivalents")) or 0

        return {
            "revenue": safe_float(inc.get("revenue")),
            "ebitda": safe_float(inc.get("ebitda")),
            "net_debt": debt - cash,
            "source": "fmp",
            "confidence": 0.6,
        }
    except:
        return None


# =========================================================
# MERGE ENGINE
# =========================================================

PRIORITY = {"fmp": 3, "twelvedata": 1}


def merge(*sources):
    out = {}
    score = {}

    for s in sources:
        if not s:
            continue

        src = s.get("source", "unknown")
        conf = s.get("confidence", 0.5)

        for k, v in s.items():
            if k in ("source", "confidence"):
                continue

            if v is None:
                continue

            sscore = PRIORITY.get(src, 0) + conf

            if k not in out or sscore > score[k]:
                out[k] = v
                score[k] = sscore

    return out


# =========================================================
# CORE DATA LAYER
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

async def get_stock_data(client, ticker):
    cached = get_cache(ticker)
    if cached:
        return cached

    td = await twelvedata_price(client, ticker)
    sec = await get_sec_fundamentals(ticker)

    merged = merge(td, sec)
    merged.setdefault("price", None)
    cash = merged.get("cash") or 0
    debt = merged.get("debt") or 0

    merged["net_debt"] = debt - cash
    merged["ticker"] = ticker
    merged.setdefault("shares", None)
    merged.setdefault("shares", 1)  # dočasně aby to nepadalo
    if not shares:
        return {"error": "missing shares", "data": d}
    merged.setdefault("revenue", 0)
    if td and td.get("price"):
        merged["price"] = td["price"]

    # 👇 SEM DÁŠ DEBUG
    print("========== DEBUG STOCK DATA ==========")
    print("TICKER:", ticker)
    print("TD:", td)
    print("SEC:", sec)
    print("MERGED BEFORE FINAL:", merged)
    print("======================================")

    set_cache(ticker, merged)
    save_snapshot(merged)

    return merged

# =========================================================
# VALUATION
# =========================================================


# =========================================================
# SCHEMAS
# =========================================================

class ScenarioParams(BaseModel):
    revenue_cagr: float
    ebitda_margin: float
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
    return {
        "ok": True,
        "fmp": bool(FMP_API_KEY),
        "twelvedata": bool(TD_API_KEY),
    }


@app.get("/company/{ticker}")
async def company(ticker: str):
    async with httpx.AsyncClient() as client:
        price = await twelvedata_price(client, ticker)
        sec = await get_sec_fundamentals(ticker)

        return {
            "ticker": ticker,
            "price": price,
            "fundamentals": sec
        }

@app.post("/valuation/{ticker}")
async def valuation(ticker: str, body: ValuationRequest):
    async with httpx.AsyncClient() as client:
        d = await get_stock_data(client, ticker)

        shares = d.get("shares")
        if not shares or shares == 0:
            return {"error": "missing shares", "data": d}

        input_data = {
            "revenue": d.get("revenue", 0),
            "ebitda_margin": 0.2,
            "ev_ebitda_multiple": 15,
            "net_debt": d.get("net_debt", 0),
            "shares": d.get("shares"),
            "price": d.get("price", 0)   # ← DODAT
        }

        result = run_scenarios(input_data)

        return {
            "ticker": ticker,
            "data": d,
            "valuation": result
        }

@app.post("/screener")
async def screener(data: dict):
    tickers = data.get("tickers", [])

    async with httpx.AsyncClient() as client:
        async def process(t):
            async with sem:
                d = await get_stock_data(client, t)

                shares = d.get("shares")
                if not shares or shares == 0:
                    return None

                res = run_scenarios({
                    "revenue": d.get("revenue", 0),
                    "ebitda_margin": 0.2,
                    "ev_ebitda_multiple": 15,
                    "net_debt": d.get("net_debt", 0),
                    "shares": d["shares"]
                })

                if not res or res.get("upside") is None:
                    return None

                return {
                    "ticker": t,
                    "upside": res["upside"]
                }

        results = await asyncio.gather(*(process(t) for t in tickers))

    results = [r for r in results if r is not None]

    return sorted(results, key=lambda x: x["upside"], reverse=True)
