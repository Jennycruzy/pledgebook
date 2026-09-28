import pytest

from app.amounts import parse_amount


@pytest.mark.parametrize(
    ("heard", "value", "currency"),
    [
        ("₦250,000", 250_000, "NGN"),
        ("250,000 naira", 250_000, "NGN"),
        ("₦50K", 50_000, "NGN"),
        ("fifty k", 50_000, "NGN"),
        ("₦1 million", 1_000_000, "NGN"),
        ("one million", 1_000_000, "NGN"),
        ("₦1.5 million", 1_500_000, "NGN"),
        ("one point five million", 1_500_000, "NGN"),
        ("quarter million", 250_000, "NGN"),
        ("half a million", 500_000, "NGN"),
        ("₦100,000 only", 100_000, "NGN"),
        ("a hundred thousand", 100_000, "NGN"),
        ("hundred k", 100_000, "NGN"),
        ("$500", 500, "USD"),
        ("five hundred dollars", 500, "USD"),
    ],
)
def test_clear_amounts(heard, value, currency):
    amount = parse_amount(heard)
    assert amount.minor == value
    assert amount.currency == currency
    assert amount.reason is None


@pytest.mark.parametrize("heard", ["two-fifty", "What a million!", "something unclear"])
def test_unclear_amounts_are_flagged(heard):
    amount = parse_amount(heard)
    assert amount.minor is None
    assert amount.reason


def test_in_kind_is_separate_from_money():
    amount = parse_amount("one bag of cement")
    assert amount.item == "one bag of cement"
    assert amount.minor is None
