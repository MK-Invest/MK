import datetime
import math
import requests
from collections import defaultdict
from typing import Any

HEADERS = {
    "User-Agent": "StockLens/1.0 (martin.kotek.317066@gmail.com)",
    "Accept-Encoding": "gzip, deflate",
    "Accept": "application/json"
}

SEC_CIK_URL = "https://www.sec.gov/files/company_tickers.json"


# =========================================================
# CIK MAP
# =========================================================

def get_cik_map():
    try:
        r = requests.get(SEC_CIK_URL, headers=HEADERS, timeout=30)
        r.raise_for_status()
        data = r.json()

        return {
            item["ticker"].upper(): {
                "cik": str(item["cik_str"]).zfill(10),
                "name": item.get("title", item["ticker"])
            }
            for item in data.values()
        }

    except Exception:
        return {}


# =========================================================
# SEC COMPANY FACTS
# =========================================================

def get_company_facts(cik: str):
    cik_padded = str(cik).zfill(10)
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik_padded}.json"

    try:
        r = requests.get(url, headers=HEADERS, timeout=30)

        if r.status_code != 200:
            return None

        data = r.json()

        if not isinstance(data, dict) or "facts" not in data:
            return None

        return data

    except Exception:
        return None


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


def select_best(items):
    """Vybere nejnovější FY záznam, fallback na jakýkoliv nejnovější."""
    if not items:
        return None

    annual = [i for i in items if i.get("fp") == "FY"]
    if annual:
        return max(annual, key=lambda x: x.get("end", ""))

    return max(items, key=lambda x: x.get("end", ""))


# =========================================================
# EXTRACTION HELPERS
# =========================================================

def extract_latest_value(section, concept):
    values = section.get(concept, {}).get("units", {})
    if not values:
        return None

    for unit, items in values.items():
        if not items:
            continue

        best = select_best(items)
        if not best:
            continue

        return safe_float(best.get("val"))

    return None


def extract_time_series(section, concept, n=4):
    """
    Vrátí časovou řadu posledních n skutečných čtvrtletních hodnot.

    SEC koncepty se vyskytují ve dvou formátech — závisí na firmě a konceptu:

    Formát A — "point-in-time" (Revenue, NetIncome u většiny firem):
      10-Q / Q1: pouze Q1          start=FY_start, end=Q1_end
      10-Q / Q2: pouze Q2          start=Q1_end,   end=Q2_end  ← start se posouvá
      10-Q / Q3: pouze Q3          start=Q2_end,   end=Q3_end
      → hodnoty jsou přímo quarterly, stačí vzít val

    Formát B — "YTD kumulativní" (D&A, CapEx, CFO u mnoha firem vč. Apple):
      10-Q / Q1: Q1                start=FY_start, end=Q1_end   val=Q1
      10-Q / Q2: Q1+Q2             start=FY_start, end=Q2_end   val=Q1+Q2
      10-Q / Q3: Q1+Q2+Q3         start=FY_start, end=Q3_end   val=Q1+Q2+Q3
      → start je vždy začátek FY, val roste → true quarterly = rozdíl sousedních

    Detekce: pokud Q2 i Q3 záznamy mají stejný `start` jako Q1 daného roku
    (= začátek FY), jde o YTD formát → dopočítáme rozdíly.

    Pravidla filtrování:
    - 10-Q / Q1|Q2|Q3  → použij (oba formáty)
    - 10-K / FY        → fallback pokud chybí quarterly
    - 10-K / Q1|Q2|Q3  → YTD klouzavé součty z 10-K ✗ ZAHOĎ
    - 10-Q / FY        → neobvyklé, ignoruj
    """
    values = section.get(concept, {}).get("units", {})
    if not values:
        return []

    # Preferuj USD jednotky
    items = None
    for unit, arr in values.items():
        if "USD" in unit.upper():
            items = arr
            break
    if not items:
        items = next(iter(values.values()), [])
    if not items:
        return []

    true_quarterly = []
    true_annual    = []

    for item in items:
        form = (item.get("form") or "").upper()
        fp   = (item.get("fp")   or "").upper()

        if form == "10-Q" and fp in ("Q1", "Q2", "Q3", "Q4"):
            true_quarterly.append(item)
        elif form == "10-K" and fp == "FY":
            true_annual.append(item)

    true_annual.sort(key=lambda x: x.get("end", ""), reverse=True)

    # ── Detekce a zpracování quarterly záznamů ───────────
    # Apple (a část firem) reportuje pro každý kvartál DVA záznamy:
    #   1. YTD kumulativní: start=FY_start, end=Qn_end, bez frame nebo frame=CYYYYQn (celý rok)
    #   2. Point-in-time:   start=Qn_start, end=Qn_end, frame="CYYYYQn" (přesný kvartál)
    #
    # Priorita výběru pro každý (fy, fp):
    #   a) záznam s frame ve formátu CYYYYQn  → přímá quarterly hodnota, vždy preferuj
    #   b) záznam bez frame / s jiným frame    → může být YTD, zpracuj klasicky
    #
    # Seskup podle (fy, fp), vyber nejlepší záznam.

    import re
    _CY_FRAME = re.compile(r'^CY\d{4}Q[1-4]$')

    def _frame_score(item):
        """Vyšší skóre = preferovanější záznam. Frame CYYYYQn = 2, bez frame = 0."""
        frame = item.get("frame") or ""
        if _CY_FRAME.match(frame):
            return 2
        return 0

    # Nejprve seřaď vzestupně pro správný výpočet rozdílů
    true_quarterly.sort(key=lambda x: x.get("end", ""))

    # Seskup podle fiskálního roku (fy field nebo odvození z start datumu Q1)
    fy_groups: dict = defaultdict(dict)   # {fy_key: {fp: item}}
    for item in true_quarterly:
        fy_key = item.get("fy") or item.get("start", "")[:4]
        fp     = (item.get("fp") or "").upper()
        existing = fy_groups[fy_key].get(fp)
        if existing is None:
            fy_groups[fy_key][fp] = item
        else:
            # Preferuj: 1. frame CYYYYQn, 2. pozdější end datum (novější data)
            new_score = _frame_score(item)
            old_score = _frame_score(existing)
            if new_score > old_score:
                fy_groups[fy_key][fp] = item
            elif new_score == old_score:
                # Pozdější end = aktuálnější záznam pro daný fp
                if item.get("end", "") > existing.get("end", ""):
                    fy_groups[fy_key][fp] = item

    derived_quarters = []   # výsledné true-quarterly záznamy

    for fy_key, fps in fy_groups.items():
        q1 = fps.get("Q1")
        q2 = fps.get("Q2")
        q3 = fps.get("Q3")
        q4 = fps.get("Q4")

        # Pokud má záznam frame CYYYYQn, je to přímá quarterly hodnota → point-in-time
        # Jinak zkontroluj YTD přes shodný start datum
        def is_frame_qt(item):
            return item is not None and _CY_FRAME.match(item.get("frame") or "")

        all_have_frame = all(
            is_frame_qt(fps.get(k)) for k in ("Q1", "Q2", "Q3") if fps.get(k) is not None
        )

        # Detekce YTD: žádný ze záznamů nemá frame CYYYYQn
        # A Q2/Q3 mají stejný start jako Q1
        q1_start = (q1 or {}).get("start", "")
        is_ytd = (
            not all_have_frame
            and q1_start != "" and (
                (q2 is not None and q2.get("start", "") == q1_start) or
                (q3 is not None and q3.get("start", "") == q1_start)
            )
        )

        if is_ytd:
            # Čistý YTD formát → dopočítej z rozdílů
            v1 = safe_float((q1 or {}).get("val"))
            v2 = safe_float((q2 or {}).get("val"))
            v3 = safe_float((q3 or {}).get("val"))

            if q1 and v1 is not None:
                derived_quarters.append({"end": q1["end"], "val": v1})
            if q2 and v1 is not None and v2 is not None:
                derived_quarters.append({"end": q2["end"], "val": v2 - v1})
            if q3 and v2 is not None and v3 is not None:
                derived_quarters.append({"end": q3["end"], "val": v3 - v2})

        else:
            # Smíšený formát (Apple): část záznamů má frame, část ne.
            # Pro každý fp vezmi frame-hodnotu pokud existuje,
            # jinak zkus dopočítat z YTD záznamů stejného FY.

            # Seber YTD záznamy pro tento FY (stejný start = začátek FY)
            # — jsou to záznamy BEZ frame nebo s frame=CYYYYQn celého roku
            fy_start = None
            ytd_by_end = {}   # {end_date: ytd_val}
            for fp_key in ("Q1", "Q2", "Q3"):
                item = fps.get(fp_key)
                if item is None:
                    continue
                # YTD záznam = nemá frame CYYYYQn nebo má stejný start jako Q1
                if not is_frame_qt(item):
                    if fy_start is None:
                        fy_start = item.get("start", "")
                    if item.get("start", "") == fy_start or fy_start is None:
                        v = safe_float(item.get("val"))
                        if v is not None:
                            ytd_by_end[item["end"]] = v

            # Seřaď YTD záznamy vzestupně pro výpočet rozdílů
            ytd_sorted = sorted(ytd_by_end.items())   # [(end, val), ...]

            # Přidej frame-quarterly hodnoty přímo
            frame_ends = set()
            for fp_key, item in [("Q1", q1), ("Q2", q2), ("Q3", q3), ("Q4", q4)]:
                if item and is_frame_qt(item):
                    v = safe_float(item.get("val"))
                    if v is not None:
                        derived_quarters.append({"end": item["end"], "val": v})
                        frame_ends.add(item["end"])

            # Z YTD série dopočítej chybějící quarterly hodnotuy
            # Q1 = ytd[0], Q2 = ytd[1]-ytd[0], Q3 = ytd[2]-ytd[1]
            prev_val = 0.0
            for end, ytd_val in ytd_sorted:
                if end not in frame_ends:
                    # Tento konec nemá frame-záznam → dopočítej z YTD rozdílu
                    q_val = ytd_val - prev_val
                    if q_val > 0:
                        derived_quarters.append({"end": end, "val": q_val})
                        frame_ends.add(end)
            # Dopočítej Q4 z FY − YTD_Q3 pokud chybí
            # Najdi odpovídající FY záznam (end ≈ ytd_sorted[-1].end + 1 kvartál)
            if ytd_sorted and q4 is None:
                import datetime as dt
                last_ytd_end = ytd_sorted[-1][0]
                last_ytd_val = ytd_sorted[-1][1]
                try:
                    last_dt = dt.date.fromisoformat(last_ytd_end)
                    for fy_item in true_annual:
                        fy_end_dt = dt.date.fromisoformat(fy_item["end"])
                        # Q4 end = FY end, musí být 60–135 dní po posledním YTD
                        delta = (fy_end_dt - last_dt).days
                        if 60 <= delta <= 135:
                            fy_val = safe_float(fy_item.get("val"))
                            if fy_val is not None:
                                q4_val = fy_val - last_ytd_val
                                if 0 < q4_val < fy_val * 0.5:
                                    derived_quarters.append({"end": fy_item["end"], "val": q4_val})
                            break
                except Exception:
                    pass

    # Seřaď sestupně a deduplikuj podle `end`
    derived_quarters.sort(key=lambda x: x["end"], reverse=True)
    seen = set()
    unique_q = []
    for q in derived_quarters:
        if q["end"] not in seen:
            seen.add(q["end"])
            unique_q.append(q)

    # ── Globální Q4 derivace ──────────────────────────────
    # Pro každý FY annual záznam zkontroluj jestli chybí Q4 (= záznam jehož end
    # je blízký FY end). Pokud máme Q1+Q2+Q3 daného FY, dopočítej Q4.
    # Tím opravíme případy jako PFE kde Q4 není v 10-Q ale máme frame-quarterly Q1-Q3.
    import datetime as _dt

    def _parse_date(d):
        try:
            return _dt.date.fromisoformat(d)
        except Exception:
            return None

    for fy_item in true_annual:
        fy_end = _parse_date(fy_item.get("end", ""))
        fy_val = safe_float(fy_item.get("val"))
        if fy_end is None or fy_val is None:
            continue

        # FY začátek ≈ fy_end − 365 dní
        fy_start_approx = fy_end - _dt.timedelta(days=370)

        # Najdi Q1, Q2, Q3 patřící do tohoto FY
        fy_quarters_found = [
            q for q in unique_q
            if not q.get("is_annual")
            and _parse_date(q["end"]) is not None
            and fy_start_approx < _parse_date(q["end"]) <= fy_end
        ]

        # Zkontroluj jestli Q4 (= záznam s end blízkým fy_end) chybí
        q4_exists = any(
            abs((_parse_date(q["end"]) - fy_end).days) <= 45
            for q in fy_quarters_found
        )

        if not q4_exists and len(fy_quarters_found) >= 1:
            q_sum = sum(q["val"] for q in fy_quarters_found)
            q4_val = fy_val - q_sum
            # Sanity: Q4 musí být kladný a rozumný (max 50 % FY)
            if 0 < q4_val <= fy_val * 0.5:
                q4_end = fy_item["end"]   # Q4 end = FY end
                if q4_end not in seen:
                    seen.add(q4_end)
                    unique_q.append({"end": q4_end, "val": q4_val, "is_q4_derived": True})

    # Znovu seřaď po přidání odvozených Q4
    unique_q.sort(key=lambda x: x["end"], reverse=True)

    if len(unique_q) >= n:
        # Hledej nejnovější okno n po sobě jdoucích kontinuálních kvartálů.
        # Pokud nejnovějších n není kontinuálních (mezera v sérii),
        # posuneme se o 1 starší a zkusíme znovu — max 4 pokusy.
        for start_idx in range(min(4, len(unique_q) - n + 1)):
            window = unique_q[start_idx: start_idx + n]
            if _quarters_are_continuous(window):
                return window
        # Žádné kontinuální okno → vrať nejnovější n (compute_ttm použije annual fallback)
        return unique_q[:n]

    # Fallback: doplň FY záznamy pokud quarterly nestačí
    # FY záznamy označíme is_annual=True aby compute_ttm věděl že nejde o quarterly
    combined = list(unique_q)
    annual_seen = set(seen)
    for fy in true_annual:
        if fy.get("end") not in annual_seen:
            annual_seen.add(fy.get("end"))
            v = safe_float(fy.get("val"))
            if v is not None:
                combined.append({"end": fy["end"], "val": v, "is_annual": True})
        if len(combined) >= n:
            break

    combined.sort(key=lambda x: x["end"], reverse=True)
    return combined[:n]


# =========================================================
# FLEXIBLE LOOKUP
# =========================================================

def pick_first_existing(section, candidates, n=4):
    for c in candidates:
        val = extract_time_series(section, c, n)
        if val:
            return val
    return []


def pick_first_existing_annual(section, candidates):
    """
    Varianta pro koncepty kde quarterly data neexistují vůbec
    a FY záznamy jsou jediným zdrojem (např. revenue u AAPL před ASC 606).
    Vrátí posledních 4 FY záznamy jako proxy časové řady.
    """
    for concept in candidates:
        values = section.get(concept, {}).get("units", {})
        if not values:
            continue

        items = None
        for unit, arr in values.items():
            if "USD" in unit.upper():
                items = arr
                break
        if not items:
            items = next(iter(values.values()), [])
        if not items:
            continue

        annual = [
            i for i in items
            if (i.get("form") or "").upper() == "10-K"
            and (i.get("fp") or "").upper() == "FY"
        ]
        if not annual:
            continue

        annual.sort(key=lambda x: x.get("end", ""), reverse=True)

        seen = set()
        result = []
        for item in annual:
            end = item.get("end")
            if end not in seen:
                seen.add(end)
                v = safe_float(item.get("val"))
                if v is not None:
                    result.append({"end": end, "val": v})
            if len(result) >= 4:
                break

        if result:
            return result

    return []


def pick_latest_scalar(section, candidates):
    for c in candidates:
        val = extract_latest_value(section, c)
        if val is not None:
            return val
    return None


# =========================================================
# TTM HELPER (standalone — sdíleno s advanced metrics)
# =========================================================

def _quarters_are_continuous(series_4: list) -> bool:
    """
    Ověří, že 4 záznamy pokrývají ~12 měsíců bez mezer.
    Kontroluje, že vzdálenost mezi každými dvěma sousedními `end` daty
    je přibližně jeden kvartál (60–135 dní).
    Záznamy musí být seřazeny sestupně (nejnovější první).
    """
    import datetime as dt

    def parse(d):
        try:
            return dt.date.fromisoformat(d)
        except Exception:
            return None

    ends = [parse(q["end"]) for q in series_4]
    if any(e is None for e in ends):
        return True  # nelze ověřit, důvěřuj

    # Zkontroluj mezery mezi sousedními záznamy (sestupně → differences jsou záporné)
    for i in range(len(ends) - 1):
        gap = (ends[i] - ends[i + 1]).days
        # Kvartál = 60–135 dní (standardní rozmezí: 91 dní ± 44 dní)
        if not (60 <= gap <= 135):
            return False

    return True


def compute_ttm(series, annual_series=None):
    """
    TTM výpočet se třemi strategiemi (v pořadí od nejpřesnější):

    1. 4 po sobě jdoucí quarterly záznamy pokrývající 12 měsíců → součet
    2. Méně než 4 quarterly, ale máme FY záznam + chybějící kvartály:
       Q4 = FY − (Q1 + Q2 + Q3)  → doplníme a sečteme
    3. Pouze FY záznam → přímo TTM (proxy)

    annual_series: volitelná řada FY záznamů pro doplnění Q4.
    Formát prvků: {"end": "YYYY-MM-DD", "val": float}
    """
    if not series:
        return None

    # Strategie 1: máme ≥ 4 quarterly — ověř kontinuitu a že nejde o mix FY+quarterly
    if len(series) >= 4:
        candidates = series[:4]
        vals = [x.get("val") for x in candidates]
        has_annual = any(x.get("is_annual") for x in candidates)
        if not any(v is None for v in vals) and not has_annual and _quarters_are_continuous(candidates):
            return sum(vals)
        # Nekontinuální nebo chybí hodnoty → padni do strategie 2/3

    # Strategie 2: Q4 dopočet z FY záznamu
    # Podmínky pro použití:
    #   a) máme 1–3 quarterly ze stejného FY
    #   b) nebo máme 4 nekontinuální quarterly + annual pro nejbližší FY
    if annual_series:
        import datetime as dt

        def parse(d):
            try:
                return dt.date.fromisoformat(d)
            except Exception:
                return None

        # Seřaď annual sestupně (nejnovější FY první)
        sorted_annual = sorted(
            [a for a in annual_series if a.get("val") is not None and parse(a.get("end", ""))],
            key=lambda x: x["end"],
            reverse=True,
        )

        for best_fy in sorted_annual:
            fy_end = parse(best_fy["end"])
            fy_val = best_fy["val"]

            # FY začátek = přibližně fy_end − 365 dní
            fy_start_approx = fy_end - dt.timedelta(days=370)

            # Quarterly patří do tohoto FY pokud jejich end je:
            # > fy_start_approx  (nezačalo před tímto FY)
            # <= fy_end          (neskončilo po tomto FY)
            fy_quarters = [
                q for q in series
                if q.get("val") is not None
                and parse(q.get("end", "")) is not None
                and fy_start_approx < parse(q["end"]) <= fy_end
            ]

            # Potřebujeme 1–3 záznamy (ne 4 — ty by prošly strategií 1)
            if not (1 <= len(fy_quarters) <= 3):
                continue

            q_sum  = sum(q["val"] for q in fy_quarters)
            q4_val = fy_val - q_sum

            # Sanity check: Q4 musí být kladný a max 40 % FY
            # (přísnější než dříve: 60 % propouštělo nesmyslné hodnoty)
            if not (fy_val and 0 < q4_val <= fy_val * 0.40):
                continue

            return fy_val  # = q_sum + q4_val

    # Strategie 3: FY záznam jako přímý TTM proxy (nejbližší dostupný)
    if annual_series:
        import datetime as dt
        def parse(d):
            try:
                return dt.date.fromisoformat(d)
            except Exception:
                return None
        sorted_annual = sorted(
            [a for a in annual_series if a.get("val") is not None],
            key=lambda x: x.get("end", ""),
            reverse=True,
        )
        if sorted_annual:
            return sorted_annual[0]["val"]

    # Poslední záchrana: máme jen 1 quarterly záznam
    if series and len(series) == 1:
        return series[0].get("val")

    return None


# =========================================================
# ADVANCED METRIC EXTRACTORS
# =========================================================

def extract_fcf(gaap: dict):
    """Free Cash Flow = CFO - CapEx (TTM)."""
    _cfo_candidates = [
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByOperatingActivities",
    ]
    _capex_candidates = [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "CapitalExpenditures",
    ]
    cfo_series   = pick_first_existing(gaap, _cfo_candidates)
    capex_series = pick_first_existing(gaap, _capex_candidates)

    # CFO a CapEx jsou v CF statement vždy YTD → annual pro Q4 dopočet
    annual_cfo   = pick_first_existing_annual(gaap, _cfo_candidates)
    annual_capex = pick_first_existing_annual(gaap, _capex_candidates)

    cfo_ttm   = compute_ttm(cfo_series,   annual_cfo)
    capex_ttm = compute_ttm(capex_series, annual_capex)

    if cfo_ttm is None or capex_ttm is None:
        return None

    # CapEx bývá v SEC záporný → abs() zajistí správný směr odečítání
    return cfo_ttm - abs(capex_ttm)


def extract_operating_working_capital(gaap: dict):
    """
    Operating Working Capital = (Current Assets - Cash) - (Current Liabilities - Short-term Debt)
    Odstraňuje čistě finanční položky, aby OWC odráželo provozní kapitál.
    """
    current_assets = pick_latest_scalar(gaap, ["AssetsCurrent"])
    current_liab   = pick_latest_scalar(gaap, ["LiabilitiesCurrent"])

    if current_assets is None or current_liab is None:
        return None

    cash           = pick_latest_scalar(gaap, ["CashAndCashEquivalentsAtCarryingValue"]) or 0
    short_term_debt = pick_latest_scalar(gaap, ["DebtCurrent"]) or 0

    return (current_assets - cash) - (current_liab - short_term_debt)


def extract_tax_rate(gaap: dict):
    """
    Efektivní daňová sazba = IncomeTaxExpenseBenefit / IncomeBeforeTax.
    Hodnoty mimo rozsah <0 %, 60 %> jsou zahozeny jako nesmyslné.
    """
    tax    = pick_latest_scalar(gaap, ["IncomeTaxExpenseBenefit"])
    pretax = pick_latest_scalar(gaap, [
        "IncomeBeforeTax",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
    ])

    if tax is None or pretax is None or pretax == 0:
        return None

    rate = tax / pretax
    if rate < 0 or rate > 0.6:
        return None

    return rate


def extract_nopat(gaap: dict):
    """NOPAT = Operating Income (TTM) × (1 - efektivní daňová sazba)."""
    _op_candidates = ["OperatingIncomeLoss"]
    op_series    = pick_first_existing(gaap, _op_candidates)
    annual_op    = pick_first_existing_annual(gaap, _op_candidates)
    op_ttm       = compute_ttm(op_series, annual_op)
    tax_rate     = extract_tax_rate(gaap)

    if op_ttm is None or tax_rate is None:
        return None

    return op_ttm * (1 - tax_rate)


def extract_roic(gaap: dict):
    """
    ROIC = NOPAT / Invested Capital
    Invested Capital = Equity + Long-term Debt + Short-term Debt - Cash

    Ochranné podmínky:
    - Záporný invested capital → firmy s masivními buybacky (AAPL-like),
      kde equity je uměle stlačena. Klasický IC není interpretovatelný → None.
    - ROIC > 300 % → téměř vždy datová chyba (špatný koncept, nekonzistentní
      period mezi NOPAT a IC). Zahazujeme, aby valuace nebyla zkreslena.
    """
    nopat  = extract_nopat(gaap)
    equity = pick_latest_scalar(gaap, ["StockholdersEquity"])

    if nopat is None or equity is None:
        return None

    long_term  = pick_latest_scalar(gaap, ["LongTermDebt"]) or 0
    short_term = pick_latest_scalar(gaap, ["DebtCurrent"]) or 0
    cash       = pick_latest_scalar(gaap, ["CashAndCashEquivalentsAtCarryingValue"]) or 0

    invested_capital = equity + long_term + short_term - cash

    # Záporný nebo nulový IC → buyback-heavy firma, IC není interpretovatelný
    if invested_capital <= 0:
        return None

    roic = nopat / invested_capital

    # ROIC > 300 % signalizuje datovou chybu (nekonzistentní periody apod.)
    if abs(roic) > 3.0:
        return None

    return roic


def extract_net_debt(gaap: dict):
    """
    Net Debt = (Long-term Debt + Short-term Debt) - Cash & Equivalents.
    Nahrazuje dřívější odvozování z debt - cash v main.py (méně přesné).
    """
    long_term  = pick_latest_scalar(gaap, [
        "LongTermDebt",
        "LongTermDebtAndCapitalLeaseObligations",
    ]) or 0
    short_term = pick_latest_scalar(gaap, ["DebtCurrent"]) or 0
    cash       = pick_latest_scalar(gaap, [
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsAndShortTermInvestments",
    ]) or 0

    return (long_term + short_term) - cash


def extract_roe(gaap: dict, net_income_ttm: float = None):
    """
    ROE = Net Income (TTM) / průměr(Equity začátek + Equity konec roku)
    Průměrné equity je standardní metodologie (Yahoo, Bloomberg, Investing.com).
    Záporné equity → ROE není interpretovatelný.
    """
    if net_income_ttm is None:
        return None

    _equity_candidates = [
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ]

    # Vezmi poslední 2 FY záznamy pro průměr
    equity_series = pick_first_existing_annual(gaap, _equity_candidates)

    if len(equity_series) >= 2:
        eq_end   = equity_series[0].get("val")
        eq_start = equity_series[1].get("val")
        if eq_end is not None and eq_start is not None and eq_end > 0 and eq_start > 0:
            avg_equity = (eq_end + eq_start) / 2
            return net_income_ttm / avg_equity

    # Fallback: aktuální equity
    equity = pick_latest_scalar(gaap, _equity_candidates)
    if equity is None or equity <= 0:
        return None
    return net_income_ttm / equity


def extract_roa(gaap: dict, net_income_ttm: float = None):
    """
    ROA = Net Income (TTM) / průměr(Total Assets začátek + konec roku)
    """
    if net_income_ttm is None:
        return None

    _assets_candidates = ["Assets"]
    assets_series = pick_first_existing_annual(gaap, _assets_candidates)

    if len(assets_series) >= 2:
        a_end   = assets_series[0].get("val")
        a_start = assets_series[1].get("val")
        if a_end is not None and a_start is not None and a_end > 0 and a_start > 0:
            avg_assets = (a_end + a_start) / 2
            return net_income_ttm / avg_assets

    # Fallback: aktuální aktiva
    total_assets = pick_latest_scalar(gaap, _assets_candidates)
    if total_assets is None or total_assets == 0:
        return None
    return net_income_ttm / total_assets


def extract_current_ratio(gaap: dict):
    """Current Ratio = Current Assets / Current Liabilities"""
    current_assets = pick_latest_scalar(gaap, ["AssetsCurrent"])
    current_liab   = pick_latest_scalar(gaap, ["LiabilitiesCurrent"])
    if current_assets is None or current_liab is None or current_liab == 0:
        return None
    return current_assets / current_liab


def extract_dividends(gaap: dict):
    """
    Roční dividenda na akcii (DPS) z TTM výplat.
    Vrací absolutní částku DPS, dividendový výnos se počítá v metrics.py
    kde je k dispozici cena.
    """
    _div_candidates = [
        "PaymentsOfDividendsCommonStock",
        "PaymentsOfDividends",
        "DividendsCommonStockCash",
    ]
    _div_annual = [
        "CommonStockDividendsPerShareDeclared",
        "CommonStockDividendsPerShareCashPaid",
    ]

    # Preferuj přímé DPS koncepty (už v $/akcii)
    dps = pick_latest_scalar(gaap, _div_annual)
    if dps is not None and 0 < dps < 1000:
        return dps

    # Fallback: celkové výplaty dividend / počet akcií
    div_series  = pick_first_existing(gaap, _div_candidates)
    annual_div  = pick_first_existing_annual(gaap, _div_candidates)
    div_ttm     = compute_ttm(div_series, annual_div)
    shares      = pick_latest_scalar(gaap, [
        "CommonStockSharesOutstanding",
        "EntityCommonStockSharesOutstanding",
    ])

    if div_ttm is None or shares is None or shares == 0:
        return None

    dps = abs(div_ttm) / shares   # dividendy jsou v SEC záporné (cash outflow)
    return dps if dps < 1000 else None  # sanity cap


def extract_eps_quarterly(gaap: dict):
    """
    EPS za každý z posledních 4 kvartálů = Net Income / Shares (quarterly).
    Vrací seznam {"end": ..., "eps": ...} seřazený od nejnovějšího.
    """
    _ni_candidates = ["NetIncomeLoss", "ProfitLoss"]
    ni_series = pick_first_existing(gaap, _ni_candidates)

    shares = pick_latest_scalar(gaap, [
        "CommonStockSharesOutstanding",
        "EntityCommonStockSharesOutstanding",
    ])

    if not ni_series or shares is None or shares == 0:
        return []

    return [
        {"end": q["end"], "eps": q["val"] / shares}
        for q in ni_series[:4]
        if q.get("val") is not None
    ]
    """
    Net Debt = (Long-term Debt + Short-term Debt) - Cash & Equivalents.
    Nahrazuje dřívější odvozování z debt - cash v main.py (méně přesné).
    """
    long_term  = pick_latest_scalar(gaap, [
        "LongTermDebt",
        "LongTermDebtAndCapitalLeaseObligations",
    ]) or 0
    short_term = pick_latest_scalar(gaap, ["DebtCurrent"]) or 0
    cash       = pick_latest_scalar(gaap, [
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsAndShortTermInvestments",
    ]) or 0

    return (long_term + short_term) - cash


# =========================================================
# MAIN ENTRY
# =========================================================

def extract_fundamentals(data: dict) -> dict:
    facts = data.get("facts", {})

    gaap = facts.get("us-gaap", {}) or {}
    dei  = facts.get("dei", {}) or {}

    result = {}

    # ── Shares ───────────────────────────────────────────
    shares = pick_latest_scalar(gaap, [
        "EntityCommonStockSharesOutstanding",
        "CommonStockSharesOutstanding",
    ]) or pick_latest_scalar(dei, [
        "EntityCommonStockSharesOutstanding",
        "CommonStockSharesOutstanding",
    ])
    result["shares"] = shares

    # ── Časové řady ──────────────────────────────────────
    # Pořadí: od nejpřesnějšího po nejobecnější.
    # AAPL používá RevenueFromContractWithCustomerExcludingAssessedTax pro quarterly.
    # SalesRevenueNet a SalesRevenueGoodsNet jsou starší standardy (pre-ASC 606).
    _revenue_candidates = [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
        "SalesRevenueGoodsNet",
        "RevenuesNetOfInterestExpense",
    ]

    # Hledej první koncept který vrátí čerstvá data (nejstarší záznam < 2 roky)
    # Tím přeskočíme koncepty s historickými daty (např. Pfizer před Upjohn spinoffem)
    _two_years_ago = str(datetime.date.today().year - 2)
    revenue_series = []

    for _concept in _revenue_candidates:
        _s = extract_time_series(gaap, _concept, n=5)
        if not _s:
            continue
        # Přijmeme sérii jen pokud nejnovější záznam je čerstvý (< 2 roky)
        if _s[0]["end"][:4] >= _two_years_ago:
            revenue_series = _s
            break

    # Pokud quarterly nevráti nic čerstvého, použij FY záznamy
    if not revenue_series:
        annual_fallback = pick_first_existing_annual(gaap, _revenue_candidates)
        if annual_fallback and annual_fallback[0]["end"][:4] >= _two_years_ago:
            revenue_series = annual_fallback

    net_income_series = pick_first_existing(gaap, [
        "NetIncomeLoss",
        "ProfitLoss",
    ], n=5)

    operating_series = pick_first_existing(gaap, [
        "OperatingIncomeLoss",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesDomestic",
        "OperatingIncomeLossFromContinuingOperations",
    ], n=5)

    # Depreciation: AAPL a část firem reportuje D&A primárně v cash flow
    # statement pod odlišnými koncepty než v income statement.
    depreciation_series = pick_first_existing(gaap, [
        "DepreciationAndAmortization",
        "DepreciationDepletionAndAmortization",
        "Depreciation",
        "DepreciationAmortizationAndAccretion",          # CF statement, AAPL
        "OtherDepreciationAndAmortization",
        "AmortizationOfIntangibleAssets",                # softwarové firmy
    ], n=5)

    # ── Rozvaha (skaláry) ────────────────────────────────
    debt = pick_latest_scalar(gaap, [
        "LongTermDebt",
        "LongTermDebtAndCapitalLeaseObligations",
        "DebtCurrent",
    ])
    cash = pick_latest_scalar(gaap, [
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsAndShortTermInvestments",
    ])
    equity = pick_latest_scalar(gaap, [
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ])

    if debt   is not None: result["debt"]   = debt
    if cash   is not None: result["cash"]   = cash
    if equity is not None: result["equity"] = equity

    result["history"] = {
        "revenue":          revenue_series,
        "net_income":       net_income_series,
        "operating_income": operating_series,
        "depreciation":     depreciation_series,
    }

    # ── FY záznamy pro Q4 dopočet v compute_ttm ──────────
    # Stejná staleness logika jako pro revenue_series —
    # přeskočíme koncepty s historickými daty (např. PFE před Upjohn spinoffem)
    annual_revenue = []
    for _concept in _revenue_candidates:
        _a = pick_first_existing_annual(gaap, [_concept])
        if _a and _a[0]["end"][:4] >= _two_years_ago:
            annual_revenue = _a
            break

    annual_net_income = pick_first_existing_annual(gaap, ["NetIncomeLoss", "ProfitLoss"])
    annual_operating  = pick_first_existing_annual(gaap, ["OperatingIncomeLoss"])

    # ── TTM ──────────────────────────────────────────────
    revenue_ttm    = compute_ttm(revenue_series,    annual_revenue)
    net_income_ttm = compute_ttm(net_income_series, annual_net_income)

    if revenue_ttm    is not None: result["revenue"]    = revenue_ttm
    if net_income_ttm is not None: result["net_income"] = net_income_ttm

    # ── EBITDA margin pro valuation model ────────────────
    annual_dep = pick_first_existing_annual(gaap, [
        "DepreciationAndAmortization",
        "DepreciationDepletionAndAmortization",
        "Depreciation",
        "DepreciationAmortizationAndAccretion",
        "OtherDepreciationAndAmortization",
    ])
    op_ttm  = compute_ttm(operating_series,    annual_operating)
    dep_ttm = compute_ttm(depreciation_series, annual_dep)

    if op_ttm is not None and dep_ttm is not None and revenue_ttm:
        ebitda_ttm = op_ttm + dep_ttm
        result["ebitda"]        = ebitda_ttm
        result["ebitda_margin"] = ebitda_ttm / revenue_ttm

    # Fallback EBITDA = net_income + tax + interest + D&A
    # Použij pokud operating_income chybí ale máme D&A a net_income
    if "ebitda" not in result and dep_ttm is not None and net_income_ttm is not None:
        _interest_candidates = ["InterestExpense", "InterestAndDebtExpense"]
        _tax_candidates      = ["IncomeTaxExpenseBenefit"]

        interest_ttm = compute_ttm(
            pick_first_existing(gaap, _interest_candidates),
            pick_first_existing_annual(gaap, _interest_candidates),
        ) or 0
        tax_ttm = compute_ttm(
            pick_first_existing(gaap, _tax_candidates),
            pick_first_existing_annual(gaap, _tax_candidates),
        ) or 0

        ebitda_fallback = net_income_ttm + abs(tax_ttm) + abs(interest_ttm) + dep_ttm
        if ebitda_fallback > 0 and revenue_ttm:
            result["ebitda"]        = ebitda_fallback
            result["ebitda_margin"] = ebitda_fallback / revenue_ttm

    # ── Advanced metrics ─────────────────────────────────
    fcf      = extract_fcf(gaap)
    owc      = extract_operating_working_capital(gaap)
    tax      = extract_tax_rate(gaap)
    nopat    = extract_nopat(gaap)
    roic     = extract_roic(gaap)
    net_debt = extract_net_debt(gaap)

    # Rozvahové / výnosové metriky
    total_assets   = pick_latest_scalar(gaap, ["Assets"])
    current_assets = pick_latest_scalar(gaap, ["AssetsCurrent"])
    current_liab   = pick_latest_scalar(gaap, ["LiabilitiesCurrent"])

    roe           = extract_roe(gaap, net_income_ttm)
    roa           = extract_roa(gaap, net_income_ttm)
    current_ratio = extract_current_ratio(gaap)
    dps           = extract_dividends(gaap)
    eps_quarterly = extract_eps_quarterly(gaap)

    if fcf           is not None: result["fcf"]                       = fcf
    if owc           is not None: result["operating_working_capital"] = owc
    if tax           is not None: result["tax_rate"]                  = tax
    if nopat         is not None: result["nopat"]                     = nopat
    if roic          is not None: result["roic"]                      = roic
    if net_debt      is not None: result["net_debt"]                  = net_debt
    if total_assets  is not None: result["total_assets"]              = total_assets
    if current_assets is not None: result["current_assets"]           = current_assets
    if current_liab  is not None: result["current_liabilities"]       = current_liab
    if roe           is not None: result["roe"]                       = roe
    if roa           is not None: result["roa"]                       = roa
    if current_ratio is not None: result["current_ratio"]             = current_ratio
    if dps           is not None: result["dps"]                       = dps
    if eps_quarterly:             result["eps_quarterly"]             = eps_quarterly

    return result
