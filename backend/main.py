import asyncio
import os
import time
import math
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Query
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

# =========================================================
# CONFIG
# =========================================================

FMP_STABLE = "https://financialmodelingprep.com/stable"
FMP_API_KEY = os.getenv("FMP_API_KEY", "")
TD_API_KEY = os.getenv("TWELVEDATA_API_KEY", "")

CACHE_TTL = 300
_cache = {}

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
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
            "Accept": "application/json,text/plain,*/*",
        }

        r = await client.get(
            url,
            params=params,
            timeout=17,
            headers=headers,
        )

        if r.status_code != 200:
            return None

        return r.json()

    except:
        return None

# =========================================================
# PROVIDERS
# =========================================================

# -------------------------
# YAHOO (PRIMARY)
# -------------------------

async def yahoo_quote(client, ticker):
    data = await safe_get(
        client,
        f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{ticker}",
        params={"modules": "price,defaultKeyStatistics"},
    )

    if not data:
        return None

    try:
        result = data.get("quoteSummary", {}).get("result") or []
        if not result:
            return None

        res = result[0] or {}

        price = safe_float(
            res.get("price", {})
            .get("regularMarketPrice", {})
            .get("raw")
        )

        shares = safe_float(
            res.get("defaultKeyStatistics", {})
            .get("sharesOutstanding", {})
            .get("raw")
        )

        if price is None and shares is None:
            return None

        return {
            "price": price,
            "shares": shares,
            "source": "yahoo",
            "confidence": 0.8,
        }

    except:
        return None


async def yahoo_search(client, query):
    if not query:
        return []

    data = await safe_get(
        client,
        "https://query1.finance.yahoo.com/v1/finance/search",
        params={"q": query},
    )

    if not data:
        return []

    return [
        {
            "symbol": x.get("symbol"),
            "name": x.get("shortname") or x.get("longname"),
        }
        for x in data.get("quotes", [])
        if x.get("symbol")
    ]

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

        return {
            "revenue": safe_float(inc.get("revenue")),
            "ebitda": safe_float(inc.get("ebitda")),
            debt = safe_float(bal.get("totalDebt")) or 0
            cash = safe_float(bal.get("cashAndCashEquivalents")) or 0
            "net_debt": debt - cash,
            "source": "fmp",
            "confidence": 0.6,
        }
    except:
        return None


# =========================================================
# MERGE ENGINE
# =========================================================

PRIORITY = {"fmp": 3, "yahoo": 2, "twelvedata": 1}


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

async def get_stock_data(client, ticker):
    cached = get_cache(ticker)
    if cached:
        return cached

    yahoo = await yahoo_quote(client, ticker)

    td = None
    if not yahoo or not yahoo.get("price"):
        td = await twelvedata_price(client, ticker)

    fmp = await fmp_fundamentals(client, ticker)

    merged = merge(yahoo, td, fmp)

    merged["ticker"] = ticker
    merged.setdefault("price", 0)
    merged.setdefault("shares", None)
    merged.setdefault("revenue", 0)
    merged.setdefault("net_debt", 0)

    set_cache(ticker, merged)
    return merged


# =========================================================
# VALUATION
# =========================================================

def compute_scenario(
    *,
    revenue,
    revenue_cagr,
    ebitda_margin,
    ev_ebitda_multiple,
    net_debt,
    shares,
    price,
    required_return,
    years,
):
    if not price or not shares:
        return None

    projected_revenue = revenue * (1 + revenue_cagr) ** years
    projected_ebitda = projected_revenue * ebitda_margin

    exit_ev = projected_ebitda * ev_ebitda_multiple
    equity = exit_ev - (net_debt or 0)

    exit_price = equity / shares
    intrinsic = exit_price / (1 + required_return) ** years

    return {
        "projected_revenue": round(projected_revenue, 0),
        "projected_ebitda": round(projected_ebitda, 0),
        "exit_price": round(exit_price, 2),
        "intrinsic_value": round(intrinsic, 2),
        "upside": round((intrinsic / price - 1), 4),
    }


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


@app.get("/search")
async def search(query: str = Query(..., alias="q")):
    async with httpx.AsyncClient() as client:
        return await yahoo_search(client, query)


@app.get("/company/{ticker}")
async def company(ticker: str):
    async with httpx.AsyncClient() as client:
        yahoo = await yahoo_quote(client, ticker)
        fmp = await fmp_fundamentals(client, ticker)
        return merge(yahoo, fmp)


@app.post("/valuation/{ticker}")
async def valuation(ticker: str, body: ValuationRequest):
    async with httpx.AsyncClient() as client:
        d = await get_stock_data(client, ticker)

        if not d.get("shares"):
            return {"error": "missing shares", "data": d}

        base = body.base or ScenarioParams(0.08, 0.2, 15)

        result = compute_scenario(
            revenue=d.get("revenue", 0),
            revenue_cagr=base.revenue_cagr,
            ebitda_margin=base.ebitda_margin,
            ev_ebitda_multiple=base.ev_ebitda_multiple,
            net_debt=d.get("net_debt", 0),
            shares=d["shares"],
            price=d.get("price", 0),
            required_return=body.required_return,
            years=body.years,
        )

        return {"ticker": ticker, "data": d, "valuation": result}


@app.post("/screener")
async def screener(data: dict):
    tickers = data.get("tickers", [])

    async with httpx.AsyncClient() as client:
        results = []

        async def process(t):
            d = await get_stock_data(client, t)

            if not d.get("shares"):
                return

            res = compute_scenario(
                revenue=d.get("revenue", 0),
                revenue_cagr=0.08,
                ebitda_margin=0.2,
                ev_ebitda_multiple=15,
                net_debt=d.get("net_debt", 0),
                shares=d["shares"],
                price=d.get("price", 0),
                required_return=0.12,
                years=2,
            )

            if res and res.get("upside") is not None:
                results.append({"ticker": t, "upside": res["upside"]})

        await asyncio.gather(*[process(t) for t in tickers])

    return sorted(results, key=lambda x: x["upside"], reverse=True)
