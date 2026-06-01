import requests
import time

CACHE_TTL = 24 * 60 * 60  # 24h
_cache = {
    "data": None,
    "time": 0
}

HEADERS = {
    "User-Agent": "StockLens EU Loader/1.0"
}


# =========================================================
# Euronext (Paris, Amsterdam, Brussels, Lisbon)
# =========================================================

def load_euronext():
    """
    Euronext má veřejné listing endpointy, ale nejsou stabilní API.
    Používáme fallback JSON exporty / snapshoty.
    """

    urls = [
        "https://www.euronext.com/en/ajax/content/companies?format=json",
    ]

    tickers = {}

    for url in urls:
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            if r.status_code != 200:
                continue

            data = r.json()

            for item in data.get("data", []):
                symbol = item.get("symbol")
                name = item.get("name")

                if symbol:
                    tickers[symbol.upper()] = {
                        "name": name,
                        "exchange": "EURONEXT",
                        "country": item.get("country"),
                    }

        except Exception:
            continue

    return tickers


# =========================================================
# XETRA (Deutsche Börse)
# =========================================================

def load_xetra():
    """
    Xetra nemá jednoduché free API → používáme veřejné symbol datasets.
    """

    url = "https://api.stooq.com/q/l/?s=&f=sd2t2ohlcv&h&e=json"

    tickers = {}

    try:
        # Stooq dataset fallback (nejpraktičtější free source)
        r = requests.get(url, headers=HEADERS, timeout=20)
        if r.status_code != 200:
            return {}

        data = r.json()

        for item in data.get("data", []):
            symbol = item.get("symbol", "")
            if "." in symbol:  # EU styl (SAP.DE, VOW3.DE)
                tickers[symbol.upper()] = {
                    "name": symbol,
                    "exchange": "XETRA",
                }

    except Exception:
        pass

    # fallback ručně známé core tickery (stabilita)
    manual = {
        "SAP.DE": {"name": "SAP", "exchange": "XETRA"},
        "SIE.DE": {"name": "Siemens", "exchange": "XETRA"},
        "BMW.DE": {"name": "BMW", "exchange": "XETRA"},
        "VOW3.DE": {"name": "Volkswagen", "exchange": "XETRA"},
        "DTE.DE": {"name": "Deutsche Telekom", "exchange": "XETRA"},
    }

    tickers.update(manual)
    return tickers


# =========================================================
# PRAHA (PSE)
# =========================================================

def load_pse():
    """
    Praha Stock Exchange (PSE) – české akcie.
    Free dataset není stabilní → kombinace manual + snapshot.
    """

    tickers = {
        "CEZ.PR": {"name": "ČEZ", "exchange": "PSE"},
        "KOF.PR": {"name": "Kofola", "exchange": "PSE"},
        "MONET.PR": {"name": "Moneta Money Bank", "exchange": "PSE"},
        "CZG.PR": {"name": "Colt CZ Group", "exchange": "PSE"},
        "ERG.PR": {"name": "Erste Group", "exchange": "PSE"},
    }

    return tickers


# =========================================================
# PUBLIC LOADER
# =========================================================

def get_eu_universe(force_refresh=False):
    global _cache

    now = time.time()

    if (
        not force_refresh
        and _cache["data"] is not None
        and now - _cache["time"] < CACHE_TTL
    ):
        return _cache["data"]

    universe = {}

    # load sources
    universe.update(load_euronext())
    universe.update(load_xetra())
    universe.update(load_pse())

    _cache["data"] = universe
    _cache["time"] = now

    return universe


# =========================================================
# SEARCH HELPER
# =========================================================

def search_eu(query: str):
    q = query.upper()
    universe = get_eu_universe()

    exact = []
    partial = []

    for ticker, meta in universe.items():
        if ticker == q:
            exact.append({"symbol": ticker, **meta})
        elif q in ticker or (meta.get("name", "").upper().find(q) >= 0):
            partial.append({"symbol": ticker, **meta})

    return exact + partial
