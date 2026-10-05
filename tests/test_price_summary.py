"""Resumen de precios para /precios."""

from datetime import datetime, timezone

from app.config.settings import Settings
from app.notifications.telegram_commands import CommandHandlers, TelegramCommandPoller
from app.services.price_summary import PriceRow, prices_text

T = datetime(2026, 10, 5, 13, 0, tzinfo=timezone.utc)
ROWS = [
    PriceRow("Gamaex", "USD", 960, 985, T),
    PriceRow("Cambios Lyon", "USD", 965, 990, T),
    PriceRow("Cambio Costero", "USD", None, 988, T),
    PriceRow("Inmonex", "EUR", 1100, 1130, T),
    PriceRow("Orion", "COP", 0.28, 0.33, T),
]


def test_overview_shows_best_place_to_buy_and_sell():
    text = prices_text(ROWS)
    assert "USD: comprar en Gamaex a 985 · vender en Cambios Lyon a 965" in text
    assert "EUR: comprar en Inmonex a 1.130 · vender en Inmonex a 1.100" in text
    assert "Otras divisas: COP." in text


def test_detail_lists_every_house_with_local_time():
    text = prices_text(ROWS, "USD")
    assert text.splitlines()[1] == "• Gamaex: 960 / 985 (10:00)"  # 13:00 UTC = 10:00 en Santiago (horario de verano)
    assert "• Cambio Costero: — / 988 (10:00)" in text
    assert "No hay precios guardados de JPY" in prices_text(ROWS, "JPY")


def test_telegram_precios_command(tmp_path):
    settings = Settings(_env_file=None, telegram_bot_token="T", telegram_chat_id="42",
                        manual_quotes_file=str(tmp_path / "m.csv"))
    asked = []
    handlers = CommandHandlers(known_houses=dict, after_price=str, top=str,
                               prices=lambda c: asked.append(c) or "ok")
    poller = TelegramCommandPoller(settings, handlers, offset_file=tmp_path / "o.txt")
    assert poller.handle("/precios") == "ok" and poller.handle("/precios dolar") == "ok"
    assert asked == [None, "USD"]
    assert "No reconozco" in poller.handle("/precios xyz")
