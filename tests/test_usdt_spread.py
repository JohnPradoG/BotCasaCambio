from datetime import datetime, timedelta, timezone

from app.config.settings import Settings
from app.services import usdt_spread as us
from app.services.market_reference import MarketRef

BUDA = MarketRef("Buda.com", bid=975.0, ask=978.0, url="https://www.buda.com/chile")
BINANCE = MarketRef("Binance P2P", bid=985.0, ask=990.0, url="https://p2p.binance.com")
NOW = datetime(2026, 10, 7, 15, tzinfo=timezone.utc)


class Notifier:
    def __init__(self):
        self.sent = []

    def send(self, text):
        self.sent.append(text)
        return True


def test_best_spread_buy_cheap_sell_dear():
    best = us.find_spreads({"buda": BUDA, "binance": BINANCE}, 1_000_000, 0)[0]
    assert (best.buy_at.source, best.sell_at.source) == ("Buda.com", "Binance P2P")
    assert round(best.profit_clp) == round(1_000_000 / 978 * 985 - 1_000_000)  # +7.157
    with_fees = us.find_spreads({"buda": BUDA, "binance": BINANCE}, 1_000_000, 0.5)[0]
    assert with_fees.profit_clp < best.profit_clp


def test_text():
    text = us.spread_text(us.find_spreads({"buda": BUDA, "binance": BINANCE}, 1_000_000, 0)[0])
    assert "Comprar USDT en Buda.com a 978,00" in text and "Venderlo en Binance P2P a 985,00" in text
    assert "+$7.157" in text and "antes de comisiones" in text


def test_alert_cooldown_and_no_profit():
    settings = Settings(_env_file=None, usdt_alert_cooldown_hours=2)
    state, n = {}, Notifier()
    refs = {"buda": BUDA, "binance": BINANCE}
    assert us.check_usdt_spreads(refs, settings, n, NOW, state) == ["USDT:Buda.com>Binance P2P"]
    assert us.check_usdt_spreads(refs, settings, n, NOW + timedelta(hours=1), state) == []
    assert us.check_usdt_spreads(refs, settings, n, NOW + timedelta(hours=3), state)
    assert len(n.sent) == 2
    flat = {"buda": BUDA}  # una sola plataforma con bid < ask: no hay ganancia
    assert us.check_usdt_spreads(flat, settings, Notifier(), NOW, {}) == []
    assert us.check_usdt_spreads({}, settings, Notifier(), NOW, {}) == []


def test_fetch_all_skips_failing_venue(monkeypatch, tmp_path):
    import requests

    def boom(settings, session, asset="USDT"):
        raise requests.ConnectionError("x")

    monkeypatch.setitem(us.SOURCES, "binance", boom)
    monkeypatch.setitem(us.SOURCES, "buda", lambda settings, session, asset="USDT": BUDA)
    monkeypatch.setitem(us.SOURCES, "cryptomkt", lambda settings, session, asset="USDT": session.missing)  # error raro
    history = tmp_path / "usdt.csv"
    refs = us.fetch_all(Settings(_env_file=None, usdt_history_file=str(history), crypto_assets="USDT"), session=object(), use_cache=False)
    assert list(refs) == ["buda"]
    lines = history.read_text().splitlines()
    assert lines[0] == "at,venue,source,bid,ask,url" and ",buda,Buda.com,975.0,978.0," in lines[1]


def test_venues_text_shows_missing_platforms():
    settings = Settings(_env_file=None, usdt_venues="buda,binance,okx", crypto_assets="USDT")
    text = us.venues_text({"buda": BUDA, "binance": BINANCE}, settings)
    assert "✅ Buda.com: 978,00 / 975,00" in text and "❌ okx: no respondió" in text
    assert "Mejor: comprar en Buda.com y vender en Binance P2P: +$7.157" in text


def test_each_crypto_is_compared_only_with_itself(monkeypatch):
    btc_buda = MarketRef("Buda.com", bid=60_000_000, ask=60_100_000, url="u", asset="BTC")
    btc_binance = MarketRef("Binance P2P", bid=60_500_000, ask=60_600_000, url="u", asset="BTC")
    refs = {"buda": BUDA, "binance": BINANCE, "buda:BTC": btc_buda, "binance:BTC": btc_binance}
    spreads = us.find_spreads(refs, 1_000_000, 0)
    assert all(s.buy_at.asset == s.sell_at.asset for s in spreads)
    best_btc = next(s for s in spreads if s.buy_at.asset == "BTC")
    assert (best_btc.buy_at.source, best_btc.sell_at.source) == ("Buda.com", "Binance P2P")
    text = us.spread_text(best_btc)
    assert "DIFERENCIA BTC" in text and "comisión de retiro" in text

    calls = []

    def fake(settings, session, asset="USDT"):
        calls.append(asset)
        return MarketRef("Buda.com", 1, 2, "u", asset=asset) if asset != "ETH" else None

    monkeypatch.setitem(us.SOURCES, "buda", fake)
    got = us.fetch_all(Settings(_env_file=None, usdt_venues="buda", crypto_assets="USDT,BTC,ETH", usdt_history_file=""),
                       session=object(), use_cache=False)
    assert calls == ["USDT", "BTC", "ETH"] and list(got) == ["buda", "buda:BTC"]


def test_venues_text_shows_error_reason(monkeypatch):
    import requests

    def boom(settings, session, asset="USDT"):
        raise requests.HTTPError("403 Client Error: Forbidden")

    monkeypatch.setitem(us.SOURCES, "bybit", boom)
    monkeypatch.setitem(us.SOURCES, "buda", lambda settings, session, asset="USDT": BUDA)
    settings = Settings(_env_file=None, usdt_venues="buda,bybit", crypto_assets="USDT", usdt_history_file="")
    text = us.venues_text(us.fetch_all(settings, session=object(), use_cache=False), settings)
    assert "❌ bybit: no respondió (HTTPError: 403 Client Error: Forbidden)" in text
