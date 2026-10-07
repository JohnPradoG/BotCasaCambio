from datetime import datetime, timedelta, timezone

from app.config.settings import Settings
from app.services import usdt_backtest as bt
from app.services.market_reference import MarketRef
from app.services.usdt_spread import record

NOW = datetime(2026, 10, 7, 15, tzinfo=timezone.utc)


def _settings(tmp_path, **kw):
    return Settings(**{"_env_file": None, "respect_robots_txt": False,
                       "usdt_history_file": str(tmp_path / "usdt.csv"), **kw})


class Resp:
    def __init__(self, data):
        self.data = data

    def json(self):
        return self.data

    def raise_for_status(self):
        pass


class HistorySession:
    """Buda en dos páginas y CryptoMarket con velas; nada de red."""

    def __init__(self):
        self.calls = []

    def get(self, url, params=None, **kw):
        self.calls.append((url, dict(params or {})))
        if "cryptomkt" in url:
            return Resp([
                {"timestamp": "2026-10-07T14:00:00.000Z", "close": "990"},
                {"timestamp": "2026-10-07T13:00:00.000Z", "close": "980"},
            ])
        ms = lambda dt: str(int(dt.timestamp() * 1000))  # noqa: E731
        if "timestamp" not in (params or {}):
            entries = [[ms(NOW - timedelta(minutes=55)), "10", "981", "buy", 2],
                       [ms(NOW - timedelta(minutes=58)), "10", "979", "sell", 1]]
            return Resp({"trades": {"entries": entries, "last_timestamp": "123"}})
        old = [[ms(NOW - timedelta(days=3)), "10", "900", "buy", 0]]
        return Resp({"trades": {"entries": old, "last_timestamp": "1"}})


def test_recorded_history_finds_profit(tmp_path):
    s = _settings(tmp_path)
    at = NOW - timedelta(hours=2)
    record(s.usdt_history_file, {"buda": MarketRef("Buda.com", 975, 978, "u", at=at),
                                 "binance": MarketRef("Binance P2P", 985, 990, "u", at=at)})
    record(s.usdt_history_file, {"buda": MarketRef("Buda.com", 980, 982, "u", at=at + timedelta(minutes=30))})
    snaps = bt.load_recorded(s.usdt_history_file, NOW - timedelta(days=1))
    assert len(snaps) == 2
    r = bt.evaluate(snaps, 1_000_000, 0)
    assert r.periods == 2 and len(r.winners) == 1  # el bloque con una sola plataforma no da ganancia
    at_best, best = r.best
    assert (best.buy_at.source, best.sell_at.source) == ("Buda.com", "Binance P2P")


def test_public_history_and_text(tmp_path, monkeypatch):
    monkeypatch.setattr(bt.time, "sleep", lambda s: None)
    s = _settings(tmp_path)
    session = HistorySession()
    buda = bt.buda_history(s, session, NOW - timedelta(days=1))
    assert len(buda) == 1
    ref = next(iter(buda.values()))
    assert (ref.bid, ref.ask) == (979.0, 981.0)
    assert len([c for c in session.calls if "buda" in c[0]]) == 2  # paró al pasar la fecha pedida
    text = bt.backtest_text(s, 1, now=NOW, session=HistorySession())
    assert "Sin datos" in text  # no hay lecturas guardadas
    assert "Con ganancia: 1" in text and "CryptoMarket" in text  # Buda 981 → CryptoMarket 990
    assert "Aproximado" in text


def test_failing_platform_does_not_break(tmp_path):
    class Broken:
        def get(self, *a, **kw):
            raise ConnectionError("x")

    text = bt.backtest_text(_settings(tmp_path), 7, now=NOW, session=Broken())
    assert "No respondió: buda, cryptomkt" in text
