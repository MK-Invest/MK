"""
backend/sec/timeseries.py — extrakce čistých kvartálních časových řad
z raw SEC XBRL dat. Řeší: YTD kumulativní hodnoty, chybějící 'start' pole,
roční výkazy zahraničních emitentů (20-F), rekonstrukci Q4.
"""

import datetime

from .utils import safe_float
from .normalize import dedupe_by_end, build_q4_from_annual


def _filter_quarterly_by_delta(items, cutoff):
    """
    Filtruje záznamy kde start->end delta je 60-135 dní (čisté quarterly).
    Vrátí jen záznamy kde 'start' pole existuje.
    """
    result = []
    for i in items:
        if i.get("end", "") < cutoff or i.get("val") is None:
            continue
        start = i.get("start", "")
        end   = i.get("end", "")
        if not start:
            continue
        try:
            delta = (datetime.date.fromisoformat(end) - datetime.date.fromisoformat(start)).days
            if 60 <= delta <= 135:
                result.append({"end": end, "val": safe_float(i["val"])})
        except Exception:
            pass
    return result


def _ytd_to_quarterly(items, cutoff):
    """
    Konverze YTD kumulativních záznamů na čisté quarterly hodnoty.
    Používá se pro firmy bez 'start' pole (např. PFE) kde SEC vrací
    YTD hodnoty pod fp=Q1/Q2/Q3.

    Logika:
      Q1 = YTD_Q1
      Q2 = YTD_Q2 - YTD_Q1
      Q3 = YTD_Q3 - YTD_Q2
      Q4 = FY_annual - YTD_Q3   (z 10-K/20-F)
    """
    by_year = {}
    for i in items:
        if i.get("end", "") < cutoff or i.get("val") is None:
            continue
        year = i["end"][:4]
        fp   = i.get("fp", "")
        form = (i.get("form") or "").upper()
        v    = safe_float(i["val"])
        if v is None:
            continue
        if fp in ("Q1", "Q2", "Q3"):
            by_year.setdefault(year, {})[fp] = {"end": i["end"], "val": v}
        elif "10-K" in form or "20-F" in form or fp in ("FY", "A"):
            by_year.setdefault(year, {})["FY"] = {"end": i["end"], "val": v}

    result = []
    for year, periods in by_year.items():
        q1     = periods.get("Q1")
        q2_ytd = periods.get("Q2")
        q3_ytd = periods.get("Q3")
        fy_ann = periods.get("FY")

        if q1:
            result.append({"end": q1["end"], "val": q1["val"]})

        if q1 and q2_ytd and q2_ytd["val"] > q1["val"]:
            result.append({"end": q2_ytd["end"], "val": q2_ytd["val"] - q1["val"]})

        if q2_ytd and q3_ytd and q3_ytd["val"] > q2_ytd["val"]:
            result.append({"end": q3_ytd["end"], "val": q3_ytd["val"] - q2_ytd["val"]})

        if q3_ytd and fy_ann and fy_ann["val"] > q3_ytd["val"]:
            result.append({"end": fy_ann["end"], "val": fy_ann["val"] - q3_ytd["val"]})
        elif q1 and fy_ann and not q2_ytd and not q3_ytd:
            q4_val = fy_ann["val"] - q1["val"]
            if q4_val > 0:
                result.append({"end": fy_ann["end"], "val": q4_val})

    return result


def extract_annual_only(items: list) -> list:
    """
    Filtruje pouze 10-K/20-F (FY) záznamy s validní hodnotou.
    20-F = roční výkaz zahraničních emitentů (ADR firmy jako BABA) —
    nemají kvartální 10-Q, jen roční podání.
    """
    out = []
    for i in items:
        form = (i.get("form") or "").upper()
        fp = i.get("fp", "")
        if "10-K" in form or "20-F" in form or fp in ("FY", "A"):
            v = safe_float(i.get("val"))
            if v is not None and i.get("end"):
                out.append({"end": i["end"], "val": v})
    return out


def dedupe_annual_by_year(items: list) -> list:
    """
    Deduplikace ročních záznamů podle fiskálního roku (první 4 znaky 'end').
    Pokud SEC vrátí víc záznamů pro stejný rok (různé units/revize),
    vezme se ten s nejnovějším 'end' datem jako nejspolehlivější.
    """
    by_year = {}
    for i in items:
        fy = i["end"][:4]
        if fy not in by_year or i["end"] > by_year[fy]["end"]:
            by_year[fy] = i
    return list(by_year.values())


def extract_time_series(section, concept, n=20):
    """
    Vrátí quarterly sérii pro daný GAAP concept, nejnovější záznamy první.

    Dvě strategie podle toho co SEC vrátí:
    A) Záznamy mají 'start' pole -> delta filtr 60-135 dní (spolehlivé)
    B) Záznamy nemají 'start' pole -> YTD->quarterly konverze

    Navíc: Q4 rekonstrukce z 10-K/20-F. Fallback na roční data pokud
    žádná kvartální data nejsou dostupná (firmy s mezerami v podáních,
    zahraniční emitenti s jen ročními výkazy).
    """
    values = section.get(concept, {}).get("units", {})
    if not values:
        return []

    items = None
    for unit, arr in values.items():
        if "USD" in unit.upper():
            items = arr
            break
    if not items:
        items = next(iter(values.values()), [])
    if not items:
        return []

    cutoff_year = datetime.date.today().year - 5
    cutoff = f"{cutoff_year}-01-01"

    has_start = any(i.get("start") for i in items if i.get("end", "") >= cutoff)

    if has_start:
        quarterly = _filter_quarterly_by_delta(items, cutoff)
    else:
        quarterly = _ytd_to_quarterly(items, cutoff)

    annual = [
        i for i in items
        if (i.get("form") or "").upper() in ("10-K", "20-F")
        and i.get("end", "") >= cutoff
        and i.get("val") is not None
    ]

    reconstructed = []
    if annual:
        fy_q = {}
        for q in quarterly:
            key = q["end"][:4]
            fy_q.setdefault(key, []).append(q)

        for ann in annual:
            key = ann["end"][:4]
            qs  = sorted(fy_q.get(key, []), key=lambda x: x["end"])
            if len(qs) >= 3:
                q4 = build_q4_from_annual(qs[:3], safe_float(ann["val"]), ann["end"])
                if q4 and not any(q["end"] == q4["end"] for q in quarterly):
                    reconstructed.append(q4)

    all_items = quarterly + reconstructed

    # Fallback: pokud stále prázdné, vezmi roční záznamy přímo
    # (firmy s mezerami v podáních nebo jen ročními výkazy jako BABA)
    if not all_items:
        for ann in annual:
            v = safe_float(ann.get("val"))
            if v is not None:
                all_items.append({"end": ann["end"], "val": v})

    return dedupe_by_end(all_items)[:n]


def pick_first_existing(section, candidates, n=20):
    """
    Vrátí sérii od kandidáta s NEJNOVĚJŠÍMI daty.
    Pokud více kandidátů má záznamy, vyhraje ten s nejnovějším end datem.
    """
    best_series = []
    best_end = ""

    for c in candidates:
        s = extract_time_series(section, c, n)
        if not s:
            continue
        newest = s[0]["end"]
        if newest > best_end:
            best_end = newest
            best_series = s

    return best_series


def extract_latest_annual_series(section, candidates):
    """
    Vrátí roční (10-K/20-F, fp=FY) záznamy pro daný koncept — používá se
    jako fallback pro compute_ttm() když chybí kompletní sada 4 čistých
    kvartálů (mezera v SEC podáních, firma po restrukturalizaci/spin-offu).
    """
    for c in candidates:
        units = section.get(c, {}).get("units", {})
        for unit, items in units.items():
            if "USD" not in unit.upper():
                continue
            annual = dedupe_annual_by_year(extract_annual_only(items))
            if annual:
                return annual
    return []
