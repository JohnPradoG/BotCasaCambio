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
    assert us.check_usdt_spreads(refs, settings, n, NOW, state) == ["Buda.com>Binance P2P"]
    assert us.check_usdt_spreads(refs, settings, n, NOW + timedelta(hours=1), state) == []
    assert us.check_usdt_spreads(refs, settings, n, NOW + timedelta(hours=3), state)
    assert len(n.sent) == 2
    flat = {"buda": BUDA}  # una sola plataforma con bid < ask: no hay ganancia
    assert us.check_usdt_spreads(flat, settings, Notifier(), NOW, {}) == []
    assert us.check_usdt_spreads({}, settings, Notifier(), NOW, {}) == []


def test_fetch_all_skips_failing_venue(monkeypatch):
    import requests

    def boom(settings, session):
        raise requests.ConnectionError("x")

    monkeypatch.setitem(us.SOURCES, "binance", boom)
    monkeypatch.setitem(us.SOURCES, "buda", lambda settings, session: BUDA)
    refs = us.fetch_all(Settings(_env_file=None), session=object(), use_cache=False)
    assert list(refs) == ["buda"]
