from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.config.settings import Settings
from app.notifications.telegram_commands import CommandHandlers, TelegramCommandPoller
from app.services import p2p_maker as pm
from app.services.market_reference import MarketRef

# Precios que John vio en /usdt el 2026-10-08.
BUDA_BTC = MarketRef("Buda.com", bid=81_422_386, ask=81_698_522, url="b", asset="BTC")
NOTBANK_BTC = MarketRef("Notbank", bid=81_367_475, ask=81_629_999, url="n", asset="BTC")
BINANCE_BTC = MarketRef("Binance P2P", bid=80_782_335.93, ask=84_734_728.02, url="p", asset="BTC")
BUDA_USDT = MarketRef("Buda.com", bid=973.27, ask=979.11, url="b")
BINANCE_USDT = MarketRef("Binance P2P", bid=978.0, ask=980.0, url="p")
REFS = {"buda:BTC": BUDA_BTC, "notbank:BTC": NOTBANK_BTC, "binance:BTC": BINANCE_BTC,
        "buda": BUDA_USDT, "binance": BINANCE_USDT}
NOW = datetime(2026, 10, 8, 15, tzinfo=timezone.utc)
SETTINGS = Settings(_env_file=None)


class Notifier:
    def __init__(self):
        self.sent = []

    def send(self, text):
        self.sent.append(text)
        return True


def test_buy_on_cheapest_exchange_and_publish_under_best_ad():
    best = pm.find_plans(REFS, SETTINGS)[0]
    assert (best.buy_at.source, best.publish_on.source) == ("Notbank", "Binance P2P")
    assert best.price == int(84_734_728.02 * 0.999)
    assert round(best.profit_clp) == round(1_000_000 / 81_629_999 * best.price - 1_000_000)
    assert 35_000 < best.profit_clp < 40_000


def test_p2p_venues_are_never_used_to_buy():
    assert all(p.buy_at.source != "Binance P2P" for p in pm.find_plans(REFS, SETTINGS))


def test_text_shows_only_profitable_plans():
    text = pm.plans_text(REFS, SETTINGS)
    assert "PUBLICAR BTC EN BINANCE P2P" in text and "Compra BTC en Notbank a 81.629.999" in text
    assert "USDT" not in text  # publicar USDT bajo 980 deja pérdida: no se muestra
    assert "−$" not in text and "/gane" in text


def test_no_profit_message():
    text = pm.plans_text({"buda": BUDA_USDT, "binance": BINANCE_USDT}, SETTINGS)
    assert "sin ganancia por ahora" in text


def test_alert_threshold_and_cooldown():
    notifier, state = Notifier(), {}
    assert pm.check_p2p_plans(REFS, SETTINGS, notifier, NOW, state) == ["BTC:Binance P2P"]
    assert pm.check_p2p_plans(REFS, SETTINGS, notifier, NOW + timedelta(hours=1), state) == []
    assert pm.check_p2p_plans(REFS, SETTINGS, notifier, NOW + timedelta(hours=5), state) == ["BTC:Binance P2P"]
    high = Settings(_env_file=None, p2p_min_profit_clp=50_000)
    assert pm.check_p2p_plans(REFS, high, Notifier(), NOW, {}) == []


def test_gains_ledger(tmp_path):
    path, zone = tmp_path / "g.csv", ZoneInfo("America/Santiago")
    assert "Todavía no anotas" in pm.gains_text(path, NOW, zone)
    pm.add_gain(path, 15000, "BTC binance", NOW - timedelta(days=10))
    pm.add_gain(path, 20000, "", NOW)
    pm.add_gain(path, -5000, "", NOW)
    text = pm.gains_text(path, NOW, zone)
    assert "Hoy: +$15.000 en 2 operaciones" in text and "Total: +$30.000 en 3 operaciones" in text


def test_gane_command_parses_amount():
    got = []
    handlers = CommandHandlers(known_houses=dict, after_price=str, top=str,
                               add_gain=lambda amount, note: got.append((amount, note)) or "ok")
    poller = TelegramCommandPoller(SETTINGS, handlers)
    assert poller.handle("/gane 15.000 BTC en binance") == "ok"
    assert got == [(15000.0, "BTC en binance")]
    assert "Uso: /gane" in poller.handle("/gane mucho")
