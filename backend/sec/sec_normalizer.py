from collections import defaultdict
import datetime as dt


def _parse(d):
    try:
        return dt.date.fromisoformat(d)
    except:
        return None


def normalize_series(items):
    if not items:
        return []

    # 1) sort DESC
    items = sorted(items, key=lambda x: x["end"], reverse=True)

    # 2) dedupe by end
    seen = set()
    unique = []

    for x in items:
        if x["end"] in seen:
            continue
        seen.add(x["end"])
        unique.append(x)

    # 3) enforce date validity
    cleaned = []
    for x in unique:
        if _parse(x["end"]) is None:
            continue
        cleaned.append({
            "end": x["end"],
            "val": x["val"]
        })

    return cleaned


def group_by_fiscal_year(items):
    fy_map = defaultdict(list)

    for x in items:
        fy = x.get("end", "")[:4]
        fy_map[fy].append(x)

    return fy_map


def build_q4_from_annual(qs, annual_val, annual_end):
    if not annual_val or len(qs) < 3:
        return None

    q_sum = sum(q["val"] for q in qs[:3])
    q4 = annual_val - q_sum

    if q4 <= 0 or q4 > annual_val:
        return None

    return {
        "end": annual_end,
        "val": q4
    }
