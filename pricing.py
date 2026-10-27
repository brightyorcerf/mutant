def apply_discount(price, pct):
    if pct < 0 or pct > 100:
        raise ValueError("pct must be between 0 and 100")
    return round(price * (1 - pct / 100), 2)


def free_shipping(total):
    return total >= 50


def bulk_unit_price(qty, unit):
    if qty >= 100:
        return round(unit * 0.8, 2)
    if qty >= 10:
        return round(unit * 0.9, 2)
    return unit


def coupon_value(code, subtotal):
    code = code.strip().upper()
    if code == "SAVE10":
        return min(10.0, subtotal)
    if code == "HALF" and subtotal >= 40:
        return subtotal * 0.5
    return 0.0
