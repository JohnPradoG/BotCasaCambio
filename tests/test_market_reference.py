from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.config.settings import Settings
from app.services import market_reference as mr
from app.services.cycle_service import check_market_gaps
from app.services.price_summary import PriceRow, prices_text


class FakeResp:
    def __init__(self, data, status=200):
        self._data, self.status_code = data, status

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(str(self.status_code))


class FakeSession:
    def __init__(self, binance=None, buda=None, fail_binance=False):
        self.binance, self.buda, self.fail_binance = binance or {}, buda, fail_binance
        self.calls = []

    def post(self, url, json=None, **kw):
        self.calls.append(("post", url, json["tradeType"]))
        if self.fail_binance:
            return FakeResp({}, 500)
        price = self.binance.get(json["tradeType"])
        return FakeResp({"data": [{"adv": {"price": str(price)}}] if price else []})

    def get(self, url, **kw):
        self.calls.append(("get", url))
        return FakeResp(self.buda or {}, 200 if self.buda else 404)


def _settings(**kw):
    return Settings(**{"_env_file": None, "respect_robots_txt": False, **kw})


BUDA = {"ticker": {"max_bid": ["975.5", "CLP"], "min_ask": ["983.0", "CLP"]}}


def test_binance_first():
    ref = mr.get_reference(_settings(), FakeSession({"BUY": 981.88, "SELL": 982.0}, BUDA), use_cache=False)
    assert (ref.source, ref.bid, ref.ask) == ("Binance P2P", 982.0, 981.88)


def test_falls_back_to_buda_when_binance_fails():
    ref = mr.get_reference(_settings(), FakeSession(buda=BUDA, fail_binance=True), use_cache=False)
    assert (ref.source, ref.bid, ref.ask) == ("Buda.com", 975.5, 983.0)


def test_none_when_no_source_answers():
    assert mr.get_reference(_settings(), FakeSession(), use_cache=False) is None


def test_robots_disallow_skips_source(monkeypatch):
    monkeypatch.setattr(mr, "_allowed", lambda url, settings, name="": "buda" in url)
    session = FakeSession({"BUY": 981.0, "SELL": 982.0}, BUDA)
    ref = mr.get_reference(_settings(respect_robots_txt=True), session, use_cache=False)
    assert ref.source == "Buda.com"
    assert not [c for c in session.calls if c[0] == "post"]


def test_robots_unreadable_means_not_allowed(monkeypatch):
    monkeypatch.setattr(mr, "_robots_for", lambda *a: None)
    assert mr._allowed(mr.BUDA_URL, _settings(respect_robots_txt=True)) is False


def q(house, cur, buy, sell):
    return SimpleNamespace(exchange_house=house, currency=cur, buy_rate=buy, sell_rate=sell)


REF = mr.MarketRef("Binance P2P", bid=982.0, ask=985.0, url="https://p2p.binance.com")


def test_find_gaps():
    quotes = [q("a", "USD", 970, 975), q("b", "USD", 995, 1000), q("c", "USD", 977, 987), q("a", "EUR", 1, 2)]
    gaps = mr.find_gaps(quotes, REF, 0.3, {"a": "Casa A"})
    assert [(g.house, g.side) for g in gaps] == [("Casa A", "barato"), ("b", "caro")]
    assert gaps[0].percent == pytest.approx(7 / 982 * 100)
    text = mr.gaps_text(gaps)
    assert "Casa A vende el dólar a 975" in text and "b compra el dólar a 995" in text


def test_reference_line():
    assert "sin dato" in mr.reference_line(None)
    assert mr.reference_line(REF) == "📈 Dólar de mercado (Binance P2P, USDT): te pagan 982 · te cobran 985"


class Notifier:
    def __init__(self):
        self.sent = []

    def send(self, text):
        self.sent.append(text)
        return True


def test_market_gap_alert_cooldown():
    settings = _settings(market_alert_cooldown_hours=6)
    directory = {"a": SimpleNamespace(name="Casa A")}
    quotes = [q("a", "USD", 970, 975)]
    state, n = {}, Notifier()
    now = datetime(2026, 10, 5, 12, tzinfo=timezone.utc)
    assert check_market_gaps(quotes, REF, settings, directory, n, now=now, state=state) == ["Casa A:barato"]
    assert check_market_gaps(quotes, REF, settings, directory, n, now=now + timedelta(hours=1), state=state) == []
    assert check_market_gaps(quotes, REF, settings, directory, n, now=now + timedelta(hours=7), state=state)
    assert len(n.sent) == 2
    assert check_market_gaps(quotes, None, settings, directory, n, state=state) == []


def test_prices_text_with_market():
    now = datetime(2026, 10, 5, 12, tzinfo=timezone.utc)
    rows = [PriceRow("Gamaex", "USD", 977, 987, now), PriceRow("Barata", "USD", 960, 975, now)]
    overview = prices_text(rows, market=REF)
    assert "📈 Dólar de mercado (Binance P2P, USDT)" in overview
    detail = prices_text(rows, "USD", market=REF)
    assert "Barata: 960 / 975 (09:00) ⬇️ barato" in detail
    assert "Gamaex: 977 / 987 (09:00)\n" in detail
    assert "Dólar de mercado" not in prices_text(rows, "USD")


class TickerSession:
    def __init__(self, data, status=200):
        self.data, self.status, self.urls = data, status, []

    def get(self, url, **kw):
        self.urls.append(url)
        return FakeResp(self.data, self.status)


def test_cryptomkt_ticker():
    session = TickerSession({"ask": "990.1", "bid": "985.2", "last": "987"})
    ref = mr.from_cryptomkt(_settings(), session)
    assert (ref.source, ref.bid, ref.ask) == ("CryptoMarket", 985.2, 990.1)
    assert session.urls == [mr.CRYPTOMKT_URL]


def test_cryptomkt_without_offers_is_none():
    assert mr.from_cryptomkt(_settings(), TickerSession({"ask": None, "bid": "985"})) is None


def test_cryptomkt_robots_disallow(monkeypatch):
    monkeypatch.setattr(mr, "_allowed", lambda url, settings, name="": False)
    session = TickerSession({"ask": "990", "bid": "985"})
    assert mr.from_cryptomkt(_settings(), session) is None
    assert session.urls == []


def test_exempt_api_skips_robots(monkeypatch):
    monkeypatch.setattr(mr, "_robots_for", lambda *a: None)  # robots ilegible = no permitido
    s = _settings(respect_robots_txt=True)
    assert mr._allowed(mr.BUDA_URL, s, "buda") is True
    assert mr._allowed(mr.BUDA_URL, _settings(respect_robots_txt=True, robots_exempt_apis=""), "buda") is False


class P2PSession:
    def __init__(self):
        self.calls = []

    def post(self, url, json=None, **kw):  # Bybit
        self.calls.append(("bybit", json["side"], json["amount"]))
        price = {"1": "991.5", "0": "986.0"}[json["side"]]
        return FakeResp({"ret_code": 0, "result": {"items": [{"price": price}, {"price": "1"}]}})

    def get(self, url, params=None, **kw):  # OKX
        self.calls.append(("okx", params["side"], params["quoteMinAmountPerOrder"]))
        prices = {"sell": ["993", "992"], "buy": ["984", "985"]}[params["side"]]
        return FakeResp({"code": 0, "data": {params["side"]: [{"price": p} for p in prices]}})


def test_bybit_p2p():
    session = P2PSession()
    ref = mr.from_bybit(_settings(), session)
    assert (ref.source, ref.bid, ref.ask) == ("Bybit P2P", 986.0, 991.5)
    assert ("bybit", "1", "1000000") in session.calls


def test_okx_p2p_takes_best_price_each_side():
    ref = mr.from_okx(_settings(), P2PSession())
    assert (ref.source, ref.bid, ref.ask) == ("OKX P2P", 985.0, 992.0)


def test_p2p_without_ads_is_none():
    class Empty(P2PSession):
        def get(self, url, params=None, **kw):
            return FakeResp({"code": 0, "data": {}})

    assert mr.from_okx(_settings(), Empty()) is None
