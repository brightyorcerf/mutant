from pricing import free_shipping, bulk_unit_price, coupon_value


def test_free_shipping():
    assert free_shipping(80) is True


def test_bulk_unit_price():
    assert bulk_unit_price(200, 10) == 8.0


def test_coupon_value():
    assert coupon_value("SAVE10", 100) == 10.0


def test_free_shipping_boundary():
    assert free_shipping(50) is True
    assert free_shipping(49.99) is False


def test_bulk_unit_price_tiers():
    assert bulk_unit_price(100, 10) == 8.0
    assert bulk_unit_price(99, 10) == 9.0
    assert bulk_unit_price(9, 10) == 10


def test_coupon_value_half():
    assert coupon_value("HALF", 40) == 20.0
    assert coupon_value("HALF", 39.99) == 0.0


def test_coupon_value_unknown_code():
    assert coupon_value("NOPE", 100) == 0.0


def test_coupon_value_save10_below_cap():
    assert coupon_value("SAVE10", 5) == 5.0
