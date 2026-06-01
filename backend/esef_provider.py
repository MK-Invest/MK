import requests
from bs4 import BeautifulSoup

class ESEFProvider:
    """
    EU IFRS XBRL (inline HTML parsing)
    Pozn: veřejné endpointy se liší podle země.
    Toto je univerzální skeleton.
    """

    def get_facts(self, isin: str) -> dict:
        url = f"https://financials.example.eu/{isin}.html"

        r = requests.get(url, timeout=30)
        if r.status_code != 200:
            return {}

        soup = BeautifulSoup(r.text, "html.parser")

        facts = {}

        # minimalistický XBRL extraction skeleton
        for tag in soup.find_all(attrs={"contextref": True}):
            concept = tag.name
            value = tag.text

            if concept not in facts:
                facts[concept] = []

            facts[concept].append({
                "val": value,
                "context": tag.get("contextref")
            })

        return {"facts": {"ifrs": facts}}
