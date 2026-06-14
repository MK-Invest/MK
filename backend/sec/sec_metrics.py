import datetime as dt


def _quarters_are_continuous(series):
    if len(series) < 4:
        return False

    def parse(d):
        try:
            return dt.date.fromisoformat(d)
        except Exception:
            return None

    dates = [parse(x["end"]) for x in series[:4]]
    if any(d is None for d in dates):
        return False

    for i in range(3):
        gap = (dates[i] - dates[i + 1]).days
        if not (60 <= gap <= 135):
            return False

    return True


def compute_ttm(series, annual_series=None):
    if not series:
        return None

    if len(series) >= 4:
        cand = series[:4]
        vals = [x.get("val") for x in cand]

        if not any(v is None for v in vals) and _quarters_are_continuous(cand):
            return sum(vals)

    if annual_series:
        return annual_series[0]["val"] if annual_series else None

    return None
