def normalize_facts(raw: dict) -> dict:
    """
    Sjednocení SEC + IFRS do jednoho modelu.
    """

    gaap = raw.get("facts", {}).get("us-gaap", {})
    ifrs = raw.get("facts", {}).get("ifrs", {})

    return {
        "gaap": gaap,
        "ifrs": ifrs
    }
