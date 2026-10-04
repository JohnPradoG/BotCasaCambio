"""Planilla de casas con y sin precio (para llamar a consultar)."""

import csv
from datetime import timedelta

from app.config.settings import Settings
from app.database.models import CurrencyRow, QuoteRow
from app.models.exchange_house import Branch, ExchangeHouse
from app.models.quote import utcnow
from app.notifications.telegram_commands import CommandHandlers, TelegramCommandPoller
from app.services.house_list import WITH_PRICE, WITHOUT_PRICE, build_rows, price_status, summary, write_csv
from app.services.house_service import upsert_house


def _houses():
    return [
        ExchangeHouse(slug="gamaex", name="Gamaex", website="https://gamaex.cl", phone="+56 2 1111",
                      branches=[Branch(name="Centro", address="Agustinas 1", comuna="Santiago",
                                       opening_hours="L-V 9-18")]),
        ExchangeHouse(slug="andes", name="Cambios Andes", notes="Encontrada en OpenStreetMap (lectura automática)",
                      branches=[Branch(name="Ahumada", address="Ahumada 2", phone="+56 2 2222",
                                       source_url="https://www.openstreetmap.org/node/1")]),
        ExchangeHouse(slug="vieja", name="Cambios Vieja"),  # sin sucursales ni teléfono
    ]


def test_rows_split_houses_with_and_without_price(session, tmp_path):
    for h in _houses():
        upsert_house(session, h)
    session.flush()
    gamaex_id = upsert_house(session, _houses()[0]).id
    vieja_id = upsert_house(session, _houses()[2]).id
    session.add_all([CurrencyRow(code="USD"), CurrencyRow(code="EUR")])
    now = utcnow()
    for cur in ("USD", "EUR"):
        session.add(QuoteRow(exchange_house_id=gamaex_id, currency=cur, buy_rate=1, sell_rate=2,
                             timestamp_collected=now, source_url="x"))
    session.add(QuoteRow(exchange_house_id=vieja_id, currency="USD", buy_rate=1, sell_rate=2,
                         timestamp_collected=now - timedelta(hours=48), source_url="x"))  # vieja: no cuenta
    session.flush()

    status = price_status(session, max_age_hours=24)
    assert set(status) == {"gamaex"} and status["gamaex"].currencies == 2

    rows = build_rows(_houses(), status)
    assert [(r["estado"], r["casa"]) for r in rows] == [
        (WITHOUT_PRICE, "Cambios Andes"), (WITHOUT_PRICE, "Cambios Vieja"), (WITH_PRICE, "Gamaex")]
    andes, vieja, gamaex = rows
    assert andes["telefono"] == "+56 2 2222" and andes["origen"] == "OpenStreetMap"
    assert andes["fuente"] == "https://www.openstreetmap.org/node/1"
    assert vieja["telefono"] == "" and vieja["sucursal"] == ""  # lo desconocido queda vacío
    assert gamaex["telefono"] == "+56 2 1111" and gamaex["horario"] == "L-V 9-18" and gamaex["divisas"] == 2
    assert gamaex["ultimo_precio"]

    path = write_csv(rows, tmp_path / "casas.csv")
    assert path.read_bytes().startswith(b"\xef\xbb\xbf")
    assert len(list(csv.DictReader(path.open(encoding="utf-8-sig")))) == 3
    assert summary(rows).startswith("📋 Casas: 1 con precio, 2 sin precio (1 de ellas con teléfono).")


def test_telegram_lista_sends_the_file(tmp_path):
    settings = Settings(_env_file=None, telegram_bot_token="T", telegram_chat_id="42",
                        manual_quotes_file=str(tmp_path / "manual.csv"))
    sheet = tmp_path / "casas.csv"
    sheet.write_text("estado,casa\n", encoding="utf-8")
    sent = []

    class Session:
        def post(self, url, data=None, files=None, json=None, timeout=None):
            sent.append((url, data, files))

            class R:
                status_code = 200
            return R()

    handlers = CommandHandlers(known_houses=dict, after_price=str, top=str, house_list=lambda: (sheet, "📋 resumen"))
    poller = TelegramCommandPoller(settings, handlers, session=Session(), offset_file=tmp_path / "o.txt")
    assert poller.handle("/lista") == "📋 resumen"
    assert sent[0][0].endswith("/sendDocument") and sent[0][1]["chat_id"] == "42"
