import datetime as dt


def parse_date(d):
    try:
        return dt.date.fromisoformat(d)
    except Exception:
        return None


def infer_fiscal_year(end_date, fiscal_year_hint=None):
    """
    Normalizuje FY (nebere jen end[:4])
    """
    if fiscal_year_hint:
        return fiscal_year_hint

    d = parse_date(end_date)
    if not d:
        return None

    # default: calendar fallback
    return d.year


def infer_fiscal_quarter(fp, end_date):
    """
    fp = SEC fiscal period (Q1/Q2/Q3/Q4/A)
    fallback pokud fp chybí
    """
    if fp in ("Q1", "Q2", "Q3", "Q4"):
        return fp

    # fallback z měsíce
    d = parse_date(end_date)
    if not d:
        return None

    m = d.month
    if m in (1, 2, 3):
        return "Q1"
    if m in (4, 5, 6):
        return "Q2"
    if m in (7, 8, 9):
        return "Q3"
    return "Q4"


def normalize_series(items):
    """
    Output:
    [
        {
            end,
            val,
            fy,
            fq,
            is_annual
        }
    ]
    """

    out = []

    for i in items:
        if not i.get("end") or i.get("val") is None:
            continue

        fy = infer_fiscal_year(i["end"], i.get("fy"))
        fq = infer_fiscal_quarter(i.get("fp"), i["end"])

        out.append({
            "end": i["end"],
            "val": i["val"],
            "fy": fy,
            "fq": fq,
            "is_annual": (i.get("form") or "").upper() == "10-K"
        })

    # newest first
    out.sort(key=lambda x: x["end"], reverse=True)

    return out


def group_by_fiscal_year(series):
    """
    {fy: [quarters...]}
    """
    from collections import defaultdict

    groups = defaultdict(list)

    for s in series:
        if s["fy"] is None:
            continue
        groups[s["fy"]].append(s)

    # sort quarters inside FY
    for fy in groups:
        groups[fy].sort(key=lambda x: x["end"])

    return groups


def build_q4_from_annual(fy_group, annual_val, annual_end):
    """
    FY = Q1+Q2+Q3+Q4
    Q4 = FY - Q1-3
    """
    if len(fy_group) < 3 or annual_val is None:
        return None

    q1_3_sum = sum(x["val"] for x in fy_group[:3] if x["val"] is not None)
    q4 = annual_val - q1_3_sum

    if q4 <= 0 or q4 > annual_val:
        return None

    return {
        "end": annual_end,
        "val": q4
    }
