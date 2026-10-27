import pytest
from pricing import apply_discount


def test_apply_discount():
    assert apply_discount(200, 25) == 150.0


def test_apply_discount_rejects_bad_pct():
    with pytest.raises(ValueError):
        apply_discount(10, 101)
    with pytest.raises(ValueError):
        apply_discount(10, -1)
