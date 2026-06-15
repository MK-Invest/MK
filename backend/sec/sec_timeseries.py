import datetime as dt
from collections import defaultdict

def _parse_date(d):
    try:
        return dt.date.fromisoformat(d)
    except Exception:
        return None


def normalize_series(items):
    if not items:
        return []

    cleaned = []

    for x in items:
        end = x.get("end")
        val = x.get("val")

        if not end or val is None:
            continue

        parsed = _parse_date(end)
        if not parsed:
            continue

        try:
            val = float(val)
        except Exception:
            continue

        cleaned.append({
            "end": end,
            "val": val
        })

    # dedupe by date (KEEP latest occurrence)
    seen = set()
    unique = []

    for x in sorted(cleaned, key=lambda x: x["end"], reverse=True):
        if x["end"] not in seen:
            seen.add(x["end"])
            unique.append(x)

    # final sort DESC
    unique.sort(key=lambda x: x["end"], reverse=True)

    return unique

def safe_float(x):
    try:
        if x is None:
            return None
        return float(x)
    except Exception:
        return None


def quarters_are_continuous(series):
    if len(series) < 2:
        return True

    def parse(d):
        try:
            return dt.date.fromisoformat(d)
        except Exception:
            return None

    dates = [parse(x["end"]) for x in series]
    if any(d is None for d in dates):
        return True

    for i in range(len(dates) - 1):
        gap = (dates[i] - dates[i + 1]).days
        if not (60 <= gap <= 135):
            return False

    return True
