from backend.sec import get_cik_map
from backend.providers.sec_provider import SECProvider
from backend.providers.esef_provider import ESEFProvider

cik_map = get_cik_map()

sec_provider = SECProvider()
esef_provider = ESEFProvider()


def resolve_provider(symbol: str):
    s = symbol.upper()

    # US SEC
    if s in cik_map:
        return "SEC", cik_map[s]

    # EU heuristic (ISIN)
    if len(s) == 12 and s[:2].isalpha():
        return "ESEF", s

    return None, None


def get_provider(symbol: str):
    p, id_ = resolve_provider(symbol)

    if p == "SEC":
        return sec_provider, id_

    if p == "ESEF":
        return esef_provider, id_

    return None, None
