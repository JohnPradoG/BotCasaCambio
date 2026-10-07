from types import SimpleNamespace

import pytest

from app.services.near_miss import closest_pairs, daily_pairs, pairs_text, record


def q(house, cur, buy, sell):
    return SimpleNamespace(exchange_house=house, currency=cur, buy_rate=buy, sell_rate=sell)


# Precios reales del 5 de octubre (compra / venta de la casa).
QUOTES = [
    q("gamaex", "USD", 977, 987), q("inmonex", "USD", 970, 990),
    q("gamaex", "PEN", 284, 297), q("lyon", "PEN", 255, 280),
    q("gamaex", "EUR", 1097, 1121), q("inmonex", "EUR", 1100, 1130),
    q("solo_venta", "BRL", None, 190),
]
NAMES = {"gamaex": "Gamaex", "lyon": "Cambios Lyon", "inmonex": "Inmonex"}


def test_closest_pairs_orders_by_result():
    pairs = closest_pairs(QUOTES, 1_000_000, 0.5, NAMES)
    assert [p.currency for p in pairs] == ["PEN", "USD", "EUR"]  # BRL no tiene quién compre
    pen = pairs[0]
    assert (pen.buy_house, pen.buy_price, pen.sell_house, pen.sell_price) == ("Cambios Lyon", 280, "Gamaex", 284)
    assert pen.result_clp == pytest.approx(1_000_000 / (280 * 1.005) * 284 * 0.995 - 1_000_000)
    assert pen.result_clp == pytest.approx(4_193, abs=1)
    assert pairs[1].result_clp < 0 and pairs[1].buy_house == "Gamaex"


def test_without_margin_is_raw_gap():
    usd = [p for p in closest_pairs(QUOTES, 1_000_000, 0) if p.currency == "USD"][0]
    assert usd.result_clp == pytest.approx(1_000_000 / 987 * 977 - 1_000_000)


def test_text():
    text = pairs_text(closest_pairs(QUOTES, 1_000_000, 0.5, NAMES), 1_000_000, "T")
    assert "• PEN: comprar en Cambios Lyon a 280 y vender en Gamaex a 284 → +$4.193" in text
    assert "La primera queda a favor" in text
    losing = pairs_text(closest_pairs(QUOTES[:2], 1_000_000, 0.5, NAMES), 1_000_000, "T")
    assert "Ninguna da ganancia" in losing and "−$" in losing
    assert "No hay precios suficientes" in pairs_text([], 1_000_000, "T")


def test_record_keeps_best_of_day(tmp_path):
    path = tmp_path / "near.json"
    worse = closest_pairs([q("a", "USD", 970, 990), q("b", "USD", 975, 995)], 1_000_000, 0)
    better = closest_pairs([q("a", "USD", 980, 985)], 1_000_000, 0)
    record(path, worse, "2026-10-07", "10:00")
    record(path, better, "2026-10-07", "12:30")
    state = record(path, worse, "2026-10-07", "15:00")
    best = daily_pairs(state)[0]
    assert (best.buy_price, best.sell_price, best.at) == (985, 980, "12:30")
    assert "a las 12:30" in pairs_text(daily_pairs(state), 1_000_000, "T")
    state = record(path, worse, "2026-10-08", "09:00")  # día nuevo: empieza de cero
    assert daily_pairs(state)[0].at == "09:00"


def test_telegram_cerca_command(tmp_path):
    from app.config.settings import Settings
    from app.notifications.telegram_commands import CommandHandlers, TelegramCommandPoller

    settings = Settings(_env_file=None, telegram_bot_token="T", telegram_chat_id="42",
                        manual_quotes_file=str(tmp_path / "m.csv"))
    handlers = CommandHandlers(known_houses=dict, after_price=str, top=str, near=lambda: "cerca")
    poller = TelegramCommandPoller(settings, handlers, offset_file=tmp_path / "o.txt")
    assert poller.handle("/cerca") == "cerca"
    assert "/cerca" in poller.handle("/ayuda")
