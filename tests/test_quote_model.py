import pytest

from app.models.quote import NormalizedQuote, QuoteFlag, QuoteValidationError


def q(**kw):
    base = dict(exchange_house="casa_a", currency="USD", buy_rate=940.0, sell_rate=970.0, source_url="test://")
    base.update(kw)
    return NormalizedQuote(**base)


def test_valid_quote():
    quote = q().validate()
    assert quote.flags == set()
    assert quote.commission_unknown is True  # SPEC §16: sin comisión publicada => desconocida, no 0
    assert quote.mid_rate == 955.0


def test_inverted_spread_is_flagged_not_swapped():
    quote = q(buy_rate=980.0, sell_rate=970.0).validate()
    assert QuoteFlag.INVERTED_SPREAD in quote.flags
    assert quote.buy_rate == 980.0 and quote.sell_rate == 970.0


def test_one_side_missing_is_allowed_and_flagged():
    quote = q(sell_rate=None).validate()
    assert QuoteFlag.MISSING_SELL in quote.flags


@pytest.mark.parametrize(
    "kw",
    [
        dict(buy_rate=None, sell_rate=None),
        dict(buy_rate=-1.0),
        dict(currency="US"),
        dict(currency="CLP"),
        dict(source_url=""),
        dict(min_amount=10, max_amount=5),
    ],
)
def test_invalid_quotes(kw):
    with pytest.raises(QuoteValidationError):
        q(**kw).validate()


def test_known_commission():
    assert q(commission_percent=1.0).commission_unknown is False
