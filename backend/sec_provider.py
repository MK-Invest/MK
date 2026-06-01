from backend.sec import get_company_facts

class SECProvider:
    def get_facts(self, cik: str) -> dict:
        return get_company_facts(cik)
