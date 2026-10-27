from pricing import free_shipping, bulk_unit_price, coupon_value


def test_free_shipping():
    assert free_shipping(80) is True


def test_bulk_unit_price():
    assert bulk_unit_price(200, 10) == 8.0


def test_coupon_value():
    assert coupon_value("SAVE10", 100) == 10.0
