"""
backend/sec/ — SEC EDGAR data pipeline.

Re-exportuje veřejné API, aby `from backend.sec import get_cik_map,
get_company_facts, extract_fundamentals` v main.py fungovalo beze změny.
"""

from .client import get_cik_map, get_company_facts
from .extractor import extract_fundamentals

__all__ = [
    "get_cik_map",
    "get_company_facts",
    "extract_fundamentals",
]
