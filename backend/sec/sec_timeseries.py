import datetime as dt
from collections import defaultdict

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


def clean_and_dedupe(series):
    cleaned = [
        q for q in series
        if q.get("end") and isinstance(q.get("end"), str)
    ]

    cleaned.sort(key=lambda x: x["end"], reverse=True)

    seen = set()
    unique = []

    for q in cleaned:
        if q["end"] not in seen:
            seen.add(q["end"])
            unique.append(q)

    return unique
