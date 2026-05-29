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

app = FastAPI(title="MK-Invest")

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
_cache: dict = {}

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
            url,
            params=params,
            headers=headers,
            timeout=20,
            follow_redirects=True,
        )
        if r.status_code != 200:
            print(f"[safe_get] {url} → HTTP {r.status_code}: {r.text[:300]}")
            return None
        return r.json()
    except Exception as e:
        print(f"[safe_get] ERROR {url}: {repr(e)}")
        return None


# =========================================================
# PROVIDERS
# =========================================================

# ── Twelve Data (cena) ────────────────────────────────────

async def twelvedata_price(client: httpx.AsyncClient, ticker: str) -> dict | None:
    if not TD_API_KEY:
        return None

    data = await safe_get(
        client,
        "https://api.twelvedata.com/quote",
        params={"symbol": ticker, "apikey": TD_API_KEY},
    )
    if not data:
        return None

    # TwelveData může vrátit cenu v různých polích podle stavu trhu
    price = (
        safe_float(data.get("price"))        # real-time (otevřená burza)
        or safe_float(data.get("close"))     # zavřený trh
        or safe_float(data.get("previous_close"))  # fallback
    )
    print(f"[twelvedata_price] {ticker}: surová data={data} → price={price}")
    if not price:
        return None
    return {
        "price": price,
        "source": "twelvedata",
        "confidence": 0.5,
    }


# ── FMP (obohacení) ───────────────────────────────────────

async def fmp_fundamentals(client: httpx.AsyncClient, ticker: str) -> dict | None:
    if not FMP_API_KEY:
        return None

    try:
        income, balance = await asyncio.gather(
            safe_get(
                client,
                f"{FMP_STABLE}/income-statement",
                params={"symbol": ticker, "limit": 1, "apikey": FMP_API_KEY},
            ),
            safe_get(
                client,
                f"{FMP_STABLE}/balance-sheet-statement",
                params={"symbol": ticker, "limit": 1, "apikey": FMP_API_KEY},
            ),
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
    except Exception as e:
        print(f"[fmp_fundamentals] ERROR {ticker}: {repr(e)}")
        return None



# =========================================================
# MERGE ENGINE
# =========================================================

PRIORITY = {"fmp": 3, "twelvedata": 1, "sec": 2}


def merge(*sources) -> dict:
    """
    Sloučí více zdrojů dat podle priority a confidence.
    Vyhrává zdroj s nejvyšším PRIORITY[src] + confidence.
    """
    out: dict = {}
    score: dict = {}

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
# CORE DATA LAYER
# =========================================================

_cik_map_cache: dict | None = None


def get_cik(ticker: str) -> str | None:
    global _cik_map_cache
    if _cik_map_cache is None:
        _cik_map_cache = get_cik_map()
    return _cik_map_cache.get(ticker.upper())


async def get_sec_fundamentals(ticker: str) -> dict | None:
    cik = get_cik(ticker)
    if not cik:
        return None

    data = get_company_facts(cik)
    if not data:
        return None

    return extract_fundamentals(data)


async def get_stock_data(client: httpx.AsyncClient, ticker: str) -> dict:
    """
    Hlavní datová vrstva.  Spojuje TwelveData (cena), SEC (fundamentals)
    a FMP (obohacení) přes merge engine s prioritami.
    Výsledek se cachuje na CACHE_TTL sekund.
    """
    cached = get_cache(ticker)
    if cached:
        return cached

    # Paralelní fetch všech zdrojů
    td, sec, fmp_fund = await asyncio.gather(
        twelvedata_price(client, ticker),
        get_sec_fundamentals(ticker),
        fmp_fundamentals(client, ticker),
    )

    merged = merge(td, sec, fmp_fund)

    # Odvozené hodnoty
    cash = merged.get("cash") or 0
    debt = merged.get("debt") or 0
    if "net_debt" not in merged:
        merged["net_debt"] = debt - cash

    merged["ticker"] = ticker
    merged.setdefault("price", None)
    merged.setdefault("revenue", 0)
    merged.setdefault("shares", None)

    print(f"[get_stock_data] {ticker} | price={merged.get('price')} | td={td} | sec_keys={list((sec or {}).keys())}")

    set_cache(ticker, merged)
    save_snapshot(merged)

    return merged


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


@app.delete("/cache")
async def clear_cache():
    """Vymaže celou in-memory cache — užitečné při ladění."""
    count = len(_cache)
    _cache.clear()
    return {"cleared": count}


@app.delete("/cache/{ticker}")
async def clear_cache_ticker(ticker: str):
    """Vymaže cache pro konkrétní ticker."""
    ticker = ticker.upper()
    existed = ticker in _cache
    _cache.pop(ticker, None)
    return {"ticker": ticker, "cleared": existed}


@app.get("/company/{ticker}")
async def company(ticker: str):
    """
    Vrátí profil firmy, cenu a dostupné fundamentals.
    Sdílí get_stock_data() logiku — bez duplicit.
    """
    ticker = ticker.upper()
    async with httpx.AsyncClient() as client:
        d = await get_stock_data(client, ticker)

    return {
        "ticker": ticker,
        "price": d.get("price"),
        "fundamentals": {k: v for k, v in d.items() if k not in ("ticker",)},
    }

@app.get("/search")
def search_company(query: str):
    q = query.lower()

    results = sorted(
        COMPANIES,
        key=lambda c: (
            q not in c["symbol"].lower(),
            q not in c["name"].lower(),
        ),
    )

    filtered = [
        c for c in results
        if q in c["symbol"].lower() or q in c["name"].lower()
    ]

    return filtered[:10]

@app.post("/valuation/{ticker}")
async def valuation(ticker: str, body: ValuationRequest):
    """
    Spustí scénářový model (bear / base / bull) pro daný ticker.
    Vstupní parametry lze přepsat přes body.base.
    """
    ticker = ticker.upper()
    async with httpx.AsyncClient() as client:
        d = await get_stock_data(client, ticker)

    shares = d.get("shares")
    if not shares or shares == 0:
        raise HTTPException(status_code=422, detail=f"Chybí data o počtu akcií pro {ticker}")

    price = d.get("price")
    if not price:
        raise HTTPException(status_code=422, detail=f"Nepodařilo se načíst cenu akcie pro {ticker} — zkontroluj API klíče (TD_API_KEY, FMP_API_KEY) v logech serveru")

    # Umožní přepsat parametry z body — nulové hodnoty se ignorují a použijí se výchozí
    base_override = body.base.model_dump() if body.base else {}

    # ebitda_margin: body → SEC historická data → fallback 0.20
    sec_margin = d.get("ebitda_margin")

    input_data = {
        "revenue":            d.get("revenue") or 0,
        "ebitda_margin":      base_override.get("ebitda_margin") or sec_margin or 0.20,
        "ev_ebitda_multiple": base_override.get("ev_ebitda_multiple") or 15.0,
        "net_debt":           d.get("net_debt") or 0,
        "shares":             shares,
    }
    print(f"[valuation] {ticker} revenue={input_data['revenue']:,.0f} margin={input_data['ebitda_margin']:.2%} shares={input_data['shares']}")

    result = run_scenarios(input_data)

    return {
        "ticker": ticker,
        "price": price,
        "data": d,
        "valuation": result,
    }


@app.post("/screener")
async def screener(data: dict):
    """
    Batch valuace pro seznam tickerů.
    Výstup je seřazen podle base upside sestupně.
    """
    tickers = [str(t).upper() for t in data.get("tickers", [])]
    if not tickers:
        raise HTTPException(status_code=400, detail="Zadej alespoň jeden ticker")

    results = []

    async with httpx.AsyncClient() as client:
        async def process(ticker: str):
            async with sem:
                try:
                    d = await get_stock_data(client, ticker)

                    shares = d.get("shares")
                    if not shares or shares == 0:
                        return None

                    # Přesně 5 argumentů které přijímá value_company()
                    res = run_scenarios({
                        "revenue":            d.get("revenue") or 0,
                        "ebitda_margin":      d.get("ebitda_margin") or 0.20,
                        "ev_ebitda_multiple": 15.0,
                        "net_debt":           d.get("net_debt") or 0,
                        "shares":             shares,
                    })

                    base_price = (res.get("base") or {}).get("price")
                    if not res or base_price is None:
                        return None

                    current_price = d.get("price") or 0
                    upside = (base_price / current_price - 1) if current_price else None

                    return {
                        "ticker": ticker,
                        "price": current_price,
                        "upside": upside,
                        "valuation": res,
                    }
                except Exception as e:
                    print(f"[screener] {ticker} error: {repr(e)}")
                    return None

        gathered = await asyncio.gather(*(process(t) for t in tickers))

    results = [r for r in gathered if r is not None]
    results.sort(key=lambda x: x["upside"], reverse=True)
    return results
