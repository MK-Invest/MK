# model.py

def value_company(revenue, ebitda_margin, ev_ebitda_multiple, net_debt, shares):
    ebitda = revenue * ebitda_margin
    ev = ebitda * ev_ebitda_multiple
    equity = ev - net_debt
    price = equity / shares if shares else None

    return {
        "ebitda": ebitda,
        "ev": ev,
        "equity": equity,
        "price": price
    }

def run_scenarios(input_data):
    base = value_company(**input_data)

    bear = value_company(**{
        **input_data,
        "ebitda_margin": input_data["ebitda_margin"] * 0.8,
        "ev_ebitda_multiple": input_data["ev_ebitda_multiple"] * 0.8
    })

    bull = value_company(**{
        **input_data,
        "ebitda_margin": input_data["ebitda_margin"] * 1.2,
        "ev_ebitda_multiple": input_data["ev_ebitda_multiple"] * 1.2
    })

    return {
        "bear": bear,
        "base": base,
        "bull": bull
    }
