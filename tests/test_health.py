"""Estado de las casas leídas desde su web (/estado y aviso diario)."""

from datetime import datetime, timedelta, timezone

from app.config.settings import Settings
from app.database.models import CurrencyRow, QuoteRow, ScraperRunRow
from app.models.exchange_house import ExchangeHouse
from app.notifications.telegram_commands import CommandHandlers, TelegramCommandPoller
from app.services.health import NOT_READ, OK, OLD_PRICES, failing_readers, health_text, house_health
from app.services.house_service import upsert_house

NOW = datetime(2026, 10, 7, 15, 0, tzinfo=timezone.utc)  # 12:00 en Santiago


def _run(session, scraper, status="OK", when=NOW, error=None):
    run = ScraperRunRow(scraper=scraper, status=status, started_at=when, finished_at=when, error=error)
    session.add(run)
    session.flush()
    return run.id


def _quote(session, house_id, run_id, collected, published=None):
    session.add(QuoteRow(exchange_house_id=house_id, scraper_run_id=run_id, currency="USD", buy_rate=970,
                         sell_rate=990, timestamp_collected=collected, timestamp_source=published, source_url="x"))


def _setup(session):
    ids = {slug: upsert_house(session, ExchangeHouse(slug=slug, name=name)).id
           for slug, name in [("gamaex", "Gamaex"), ("lyon", "Cambios Lyon"), ("afex", "AFEX"), ("mano", "A Mano")]}
    session.add(CurrencyRow(code="USD"))
    session.flush()
    _quote(session, ids["gamaex"], _run(session, "gamaex"), NOW - timedelta(minutes=5))
    _quote(session, ids["lyon"], _run(session, "cambios_lyon"), NOW - timedelta(minutes=5),
           published=NOW - timedelta(days=5))
    _quote(session, ids["afex"], _run(session, "afex", when=NOW - timedelta(hours=20)), NOW - timedelta(hours=20))
    _run(session, "afex", status="STRUCTURE_CHANGED", error="no se encontraron cotizaciones")
    _quote(session, ids["mano"], _run(session, "manual_csv"), NOW - timedelta(hours=30))  # a mano: no se vigila
    session.flush()


def test_house_health_states(session):
    _setup(session)
    houses = house_health(session, NOW, stale_hours=2, usable_hours=24)
    assert [(h.house, h.state) for h in houses] == [("AFEX", NOT_READ), ("Cambios Lyon", OLD_PRICES), ("Gamaex", OK)]
    assert failing_readers(session, NOW) == {"afex": "no se encontraron cotizaciones"}

    text = health_text(houses, failing_readers(session, NOW), NOW)
    assert "1 de 3 funcionando." in text
    assert "❌ AFEX: no se lee desde 06/10 16:00" in text
    assert "⚠️ Cambios Lyon: la web muestra precios del 02/10; no se usan por viejos" in text
    assert "✅ Gamaex: leída 11:55" in text
    assert "• afex: no se encontraron cotizaciones" in text

    alert = health_text(houses, {}, NOW, only_problems=True)
    assert "Gamaex" not in alert and "AFEX" in alert and "/estado" in alert


def test_no_alert_when_all_ok(session):
    _setup(session)
    houses = [h for h in house_health(session, NOW, 2, 24) if h.state == OK]
    assert health_text(houses, {}, NOW, only_problems=True) is None
    assert "Todavía no hay" in health_text([], {}, NOW)


def test_telegram_estado_command(tmp_path):
    settings = Settings(_env_file=None, telegram_bot_token="T", telegram_chat_id="42",
                        manual_quotes_file=str(tmp_path / "m.csv"))
    handlers = CommandHandlers(known_houses=dict, after_price=str, top=str, health=lambda: "estado")
    poller = TelegramCommandPoller(settings, handlers, offset_file=tmp_path / "o.txt")
    assert poller.handle("/estado") == "estado"
