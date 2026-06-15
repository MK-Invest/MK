import datetime as dt

def compute_ttm(series, annual_series=None):
    if not series or len(series) < 4:
        return None

    vals = [x.get("val") for x in series[:4]]
    if any(v is None for v in vals):
        return None

    return sum(vals)
