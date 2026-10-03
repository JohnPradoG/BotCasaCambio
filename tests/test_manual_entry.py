"""Carga de precios a mano (CLI / Telegram)."""

import csv
from datetime import datetime, timezone

import pytest

from app.config.settings import Settings
from app.notifications.telegram_commands import CommandHandlers, TelegramCommandPoller
from app.scrapers.exchanges.manual_csv import ManualCsvScraper
from app.services.manual_entry import ManualEntryError, parse_price_command, save_manual_price

KNOWN = {"gamaex": "Gamaex", "cambios_lyon": "Cambios Lyon"}


def test_parse_price_command():
    p = parse_price_command("/precio gamaex USD 970 990", KNOWN)
    assert (p.house, p.currency, p.buy_rate, p.sell_rate) == ("gamaex", "USD", 970, 990)
    p = parse_price_command("/precio Cambios Lyon euro 1.085 -", KNOWN)
    assert (p.house, p.currency, p.buy_rate, p.sell_rate) == ("cambios_lyon", "EUR", 1085, None)
    p = parse_price_command("/precio Casa Nueva Centro BRL 180 192", KNOWN)
    assert p.house == "casa_nueva_centro"  # casa no registrada: se crea con su nombre, sin inventar datos


@pytest.mark.parametrize("text", ["/precio gamaex USD 970", "/precio gamaex XYZW 970 990", "/precio gamaex USD - -",
                                  "/precio gamaex USD abc 990", "/precio gamaex CLP 1 1"])
def test_parse_price_command_errors(text):
    with pytest.raises(ManualEntryError):
        parse_price_command(text, KNOWN)


def test_save_replaces_previous_price_and_is_read_by_scraper(tmp_path, settings):
    path = tmp_path / "manual.csv"
    path.write_text("exchange_house,currency,buy_rate,sell_rate\nx,EUR,1000,1100\n", encoding="utf-8")
    t1 = datetime(2026, 10, 3, 13, 0, tzinfo=timezone.utc)
    save_manual_price(path, parse_price_command("/precio gamaex USD 970 990", KNOWN), "manual:pizarra", when=t1)
    save_manual_price(path, parse_price_command("/precio gamaex USD 968 991", KNOWN), "manual:pizarra", when=t1)
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    assert [(r["exchange_house"], r["currency"], r["buy_rate"]) for r in rows] == [("x", "EUR", "1000"), ("gamaex", "USD", "968")]
    quotes = {q.currency: q for q in ManualCsvScraper(settings, path=path).run().quotes}
    assert quotes["USD"].sell_rate == 991 and quotes["USD"].timestamp_source == t1


class FakeSession:
    def __init__(self, updates):
        self.updates, self.sent = updates, []

    def get(self, url, params, timeout):
        class R:
            def json(inner):
                return {"ok": True, "result": self.updates}
        return R()

    def post(self, url, json, timeout):
        self.sent.append(json["text"])


def test_telegram_commands_only_from_configured_chat(tmp_path):
    settings = Settings(_env_file=None, telegram_bot_token="T", telegram_chat_id="42",
                        manual_quotes_file=str(tmp_path / "manual.csv"))
    handlers = CommandHandlers(known_houses=lambda: KNOWN, after_price=lambda: "Mejor ruta ahora: ...", top=lambda: "TOP")
    session = FakeSession([
        {"update_id": 1, "message": {"chat": {"id": 42}, "text": "/precio gamaex USD 970 990"}},
        {"update_id": 2, "message": {"chat": {"id": 999}, "text": "/precio gamaex USD 1 2"}},  # otro chat: se ignora
        {"update_id": 3, "message": {"chat": {"id": 42}, "text": "/top"}},
    ])
    poller = TelegramCommandPoller(settings, handlers, session=session, offset_file=tmp_path / "offset.txt")
    assert poller.poll_once() == 2
    assert session.sent[0].startswith("✅ Guardado: gamaex USD compra 970 · venta 990") and session.sent[1] == "TOP"
    rows = list(csv.DictReader((tmp_path / "manual.csv").open(encoding="utf-8")))
    assert len(rows) == 1 and rows[0]["source_url"] == "telegram:42"
    assert (tmp_path / "offset.txt").read_text() == "4"
    assert "Formato" in poller.handle("/precio gamaex")
