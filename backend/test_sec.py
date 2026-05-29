from sec import get_cik_map, get_company_facts

cik_map = get_cik_map()

print("AAPL CIK:", cik_map.get("AAPL"))

cik = cik_map.get("AAPL")

data = get_company_facts(cik)

print("DATA TYPE:", type(data))
print("KEYS:", data.keys() if data else None)
