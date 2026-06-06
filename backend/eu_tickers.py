import requests

EURONEXT_URL = "https://live.euronext.com/en/ajax/getFullList"
XETRA_URL = "https://api.boerse-frankfurt.de/v1/data/constituents"
PSE_CSV = "https://www.pse.cz/export/csv/seznam-akcii.csv"


def load_euronext():
    try:
        r = requests.get(EURONEXT_URL, timeout=30)
        data = r.json()

        out = {}
        for item in data.get("data", []):
            symbol = item.get("symbol")
            name = item.get("name")
            if symbol:
                out[symbol.upper()] = {
                    "name": name,
                    "exchange": "EURONEXT"
                }
        return out
    except:
        return {}


def load_xetra():
    try:
        r = requests.get(XETRA_URL, timeout=30)
        data = r.json()

        out = {}
        for item in data.get("data", []):
            symbol = item.get("isin") or item.get("symbol")
            if symbol:
                out[symbol.upper()] = {
                    "name": item.get("name"),
                    "exchange": "XETRA"
                }
        return out
    except:
        return {}


def load_pse():
    try:
        r = requests.get(PSE_CSV, timeout=30)
        lines = r.text.splitlines()

        out = {}
        for line in lines[1:]:
            parts = line.split(";")
            if len(parts) < 2:
                continue

            symbol = parts[0].strip()
            name = parts[1].strip()

            if symbol:
                out[symbol.upper()] = {
                    "name": name,
                    "exchange": "PSE"
                }

        return out
    except:
        return {}


def load_eu_tickers():
    data = {}
    data.update(load_euronext())
    data.update(load_xetra())
    data.update(load_pse())
    return data
