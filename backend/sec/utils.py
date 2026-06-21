"""
backend/sec/utils.py — sdílené pomocné funkce napříč balíčkem.
"""

import math


def safe_float(x):
    """Bezpečná konverze na float — None/NaN/Inf/neplatný string -> None."""
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
