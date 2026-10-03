from app.models.quote import NormalizedQuote, QuoteFlag
from app.services.anomaly_service import detect_anomalies


def mk(house, buy, sell, currency="USD"):
    return NormalizedQuote(exchange_house=house, currency=currency, buy_rate=buy, sell_rate=sell, source_url="test://")


def test_spec_test_12_anomalous_quote_is_flagged():
    quotes = [mk("a", 940, 970), mk("b", 945, 968), mk("c", 938, 972), mk("d", 1500, 1530)]
    flagged = detect_anomalies(quotes, threshold_percent=15, min_peers=3)
    assert [q.exchange_house for q in flagged] == ["d"]
    assert QuoteFlag.ANOMALOUS_QUOTE in quotes[3].flags
    assert all(QuoteFlag.ANOMALOUS_QUOTE not in q.flags for q in quotes[:3])


def test_not_enough_peers_means_no_judgement():
    quotes = [mk("a", 940, 970), mk("d", 1500, 1530)]
    assert detect_anomalies(quotes, min_peers=3) == []


def test_peers_from_history_are_used():
    history = {"USD": {"a": 955, "b": 956, "c": 954}}
    quotes = [mk("d", 1500, 1530)]
    assert len(detect_anomalies(quotes, history, min_peers=3)) == 1


def test_currencies_compared_separately():
    quotes = [mk("a", 940, 970), mk("b", 945, 968), mk("c", 938, 972), mk("d", 1020, 1060, "EUR")]
    assert detect_anomalies(quotes, min_peers=3) == []
