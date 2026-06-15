from collections import defaultdict
from .sec import safe_float


def extract_time_series(section, concept, n=4):
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

    # jen RAW cleanup, žádná logika
    out = []

    for i in items:
        if not i.get("end"):
            continue
        v = safe_float(i.get("val"))
        if v is None:
            continue

        out.append({
            "end": i["end"],
            "val": v,
            "form": i.get("form"),
            "fy": i.get("fy")
        })

    return out
