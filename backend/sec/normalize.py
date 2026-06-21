"""
backend/sec/normalize.py — normalizace časových řad, deduplikace,
seskupení podle fiskálního roku, rekonstrukce Q4 z ročních výkazů.
"""

import datetime
from collections import defaultdict

from .utils import safe_float


def normalize_series(items):
    """Vyčistí raw SEC záznamy na {end, val} páry, zahodí neplatné."""
    out = []
    for i in items:
        end = i.get("end")
        val = safe_float(i.get("val"))
        if end and val is not None:
            out.append({"end": end, "val": val})
    return out


def dedupe_by_end(items):
    """Deduplikace podle end data, nejnovější verze vyhrává (po sort DESC)."""
    seen = set()
    result = []
    for x in sorted(items, key=lambda x: x["end"], reverse=True):
        if x["end"] not in seen:
            seen.add(x["end"])
            result.append(x)
    return result


def group_by_fiscal_year(series):
    """Seskupí kvartální záznamy podle prvních 4 znaků 'end' data (rok)."""
    groups = defaultdict(list)
    for s in series:
        fy = s["end"][:4]
        groups[fy].append(s)
    for fy in groups:
        groups[fy].sort(key=lambda x: x["end"])
    return groups


def build_q4_from_annual(qs, annual_val, annual_end):
    """
    Rekonstruuje Q4 jako (roční hodnota - součet Q1+Q2+Q3).
    Vrací None pokud výsledek nedává smysl (<=0 nebo > roční hodnota).
    """
    if not qs or annual_val is None or len(qs) < 3:
        return None
    qsum = sum(x["val"] for x in qs[:3])
    q4 = annual_val - qsum
    if q4 <= 0 or q4 > annual_val:
        return None
    return {"end": annual_end, "val": q4}
