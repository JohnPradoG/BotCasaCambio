"""Fases 5-7: mensajes, Telegram, alertas, verificación, estadísticas y API. Datos sintéticos."""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config.settings import Settings
from app.database.db import session_scope
from app.database.models import ExecutionRow, OpportunityRow, VerificationRow
from app.models.exchange_house import Branch, ExchangeHouse
from app.models.quote import NormalizedQuote
from app.notifications.messages import format_alert, verification_messages, whatsapp_link
from app.notifications.telegram import TelegramNotifier, split_message
from app.services.arbitrage_engine import find_best_routes
from app.services.cycle_service import run_cycle
from app.services.history_service import full_report
from app.services.verification_service import InvalidTransition, change_status, expire_old


class FakeNotifier:
    def __init__(self):
        self.sent = []

    def send(self, text):
        self.sent.append(text)
        return True


def directory():
    return {
        "a": ExchangeHouse(slug="a", name="Casa A", phone="+56 2 0000 0000", whatsapp="+56 9 0000 0000",
                           branches=[Branch(name="Centro", address="Calle Falsa 1", comuna="Santiago")]),
        "b": ExchangeHouse(slug="b", name="Casa B", branches=[Branch(name="Norte")]),
    }


def routes():
    quotes = [NormalizedQuote("a", "USD", 930.0, 950.0, "test://").validate(),
              NormalizedQuote("b", "USD", 980.0, 1000.0, "test://").validate()]
    return find_best_routes(quotes, initial_amount=1_000_000, settings=Settings(_env_file=None, safety_margin_percent=0),
                            directory=directory())


@pytest.fixture
def cycle_settings(tmp_path):
    csv = tmp_path / "manual.csv"
    csv.write_text("exchange_house,currency,buy_rate,sell_rate\na,USD,930,950\nb,USD,980,1000\n", encoding="utf-8")
    return Settings(_env_file=None, safety_margin_percent=0, manual_quotes_file=str(csv),
                    houses_file=str(tmp_path / "none.json"), enabled_scrapers="manual_csv", min_net_profit_clp=10_000,
                    respect_robots_txt=False)


# ------------------------------------------------------------------ Fase 5
def test_verification_messages_spec_20():
    msgs = verification_messages(routes()[0], directory())
    assert msgs[0]["text"].startswith("Hola, quisiera cambiar aproximadamente $1.000.000 CLP a USD en efectivo.")
    assert "¿mantienen la tasa de 980,00" in msgs[1]["text"] and "USD 1.052,63" in msgs[1]["text"]
    assert msgs[0]["whatsapp_link"].startswith("https://wa.me/56900000000?text=Hola")
    assert msgs[1]["whatsapp_link"] is None  # Casa B no publica WhatsApp: no se inventa


def test_alert_format_spec_22():
    text = format_alert(routes(), directory(), 1_000_000)
    assert text.startswith("🔥 ARBITRAJE: +$31.579 con $1.000.000")
    assert "1) Casa A (Centro): compra USD a 950,00 → 1.052,63 USD" in text
    assert "Calle Falsa 1, Santiago" in text
    assert "📞 Casa B: sin teléfono ni dirección publicados" in text
    assert "⚠️ Confirma precio y disponibilidad antes de ir." in text
    assert len(text.splitlines()) <= 15  # John: la alerta larga no se leía en Telegram


def test_whatsapp_link_requires_number():
    assert whatsapp_link(None, "x") is None
    assert whatsapp_link("+56 9 1234 5678", "hola mundo") == "https://wa.me/56912345678?text=hola%20mundo"


def test_split_message():
    chunks = split_message("\n".join(["x" * 100] * 100), limit=1000)
    assert all(len(c) <= 1000 for c in chunks) and sum(c.count("x") for c in chunks) == 10_000


def test_telegram_notifier_posts():
    class Resp:
        status_code = 200
        text = "ok"

    class Sess:
        calls = []

        def post(self, url, json, timeout):
            self.calls.append((url, json))
            return Resp()

    sess = Sess()
    assert TelegramNotifier("TOKEN", "123", session=sess).send("hola")
    assert sess.calls[0][0] == "https://api.telegram.org/botTOKEN/sendMessage"
    assert sess.calls[0][1]["chat_id"] == "123"


def test_find_chat_ids():
    from app.notifications.telegram import find_chat_ids

    class Resp:
        status_code = 200

        def json(self):
            return {"ok": True, "result": [
                {"message": {"chat": {"id": 123, "type": "private", "first_name": "Ana"}}},
                {"message": {"chat": {"id": 123, "type": "private", "first_name": "Ana"}}},
            ]}

    class Sess:
        def get(self, url, timeout):
            assert url == "https://api.telegram.org/botTOKEN/getUpdates"
            return Resp()

    assert find_chat_ids("TOKEN", session=Sess()) == [{"id": 123, "type": "private", "name": "Ana"}]


def test_cycle_alerts_once_then_respects_cooldown(engine, cycle_settings):
    notifier = FakeNotifier()
    with session_scope(engine) as s:
        result = run_cycle(s, cycle_settings, notifier=notifier)
        assert result.routes and result.alerted
    with session_scope(engine) as s:
        run_cycle(s, cycle_settings, notifier=notifier)  # misma ruta, sin mejora: no se repite
    assert len(notifier.sent) == 1
    with session_scope(engine) as s:
        opps = s.scalars(select(OpportunityRow)).all()
        assert len(opps) == 2  # pero se guardan las dos detecciones (SPEC §23)
        assert [o.alerted for o in opps] == [True, False]


def test_small_profit_is_saved_but_not_alerted(engine, cycle_settings):
    notifier = FakeNotifier()
    settings = cycle_settings.model_copy(update={"min_net_profit_clp": 1_000_000})
    with session_scope(engine) as s:
        result = run_cycle(s, settings, notifier=notifier)
        assert result.routes and not result.alerted
        assert s.scalars(select(OpportunityRow)).all()
    assert notifier.sent == []


# ------------------------------------------------------------------ Fase 6
def _one_opportunity(engine, cycle_settings) -> int:
    with session_scope(engine) as s:
        run_cycle(s, cycle_settings, notifier=FakeNotifier())
        return s.scalars(select(OpportunityRow.id)).first()


def test_change_status_records_history_and_execution(engine, cycle_settings):
    opp_id = _one_opportunity(engine, cycle_settings)
    with session_scope(engine) as s:
        change_status(s, opp_id, "VERIFIED", "confirmado por teléfono", "phone")
        change_status(s, opp_id, "EXECUTED", "todo ok", final_clp=1_028_000)
    with session_scope(engine) as s:
        opp = s.get(OpportunityRow, opp_id)
        assert opp.status == "EXECUTED"
        assert [v.new_status for v in s.scalars(select(VerificationRow))] == ["VERIFIED", "EXECUTED"]
        assert s.scalars(select(ExecutionRow)).one().final_clp == 1_028_000


def test_failed_requires_reason_and_invalid_transition(engine, cycle_settings):
    opp_id = _one_opportunity(engine, cycle_settings)
    with session_scope(engine) as s:
        with pytest.raises(ValueError):
            change_status(s, opp_id, "FAILED")
        change_status(s, opp_id, "FAILED", "Casa no tenía suficiente USD al precio publicado.")
        with pytest.raises(InvalidTransition):
            change_status(s, opp_id, "DETECTED")


def test_expire_old(engine, cycle_settings):
    _one_opportunity(engine, cycle_settings)
    with session_scope(engine) as s:
        assert expire_old(s, ttl_minutes=60) == 0
        for o in s.scalars(select(OpportunityRow)):
            from datetime import timedelta

            o.detected_at = o.detected_at - timedelta(hours=2)
        s.flush()
        assert expire_old(s, ttl_minutes=60) == 1


def test_history_report(engine, cycle_settings):
    opp_id = _one_opportunity(engine, cycle_settings)
    with session_scope(engine) as s:
        change_status(s, opp_id, "FAILED", "sin stock")
        report = full_report(s)
    json.dumps(report)  # serializable
    assert report["opportunities"]["by_status"] == {"FAILED": 1}
    assert report["opportunities"]["by_currency"] == {"USD": 1}
    assert report["opportunities"]["real_rate_percent"] == 0.0
    assert report["opportunities"]["top_failure_reasons"] == {"sin stock": 1}
    assert report["best_price_leaders"]["USD"]["best_sell"] == {"a": 1}
    assert report["best_price_leaders"]["USD"]["best_buy"] == {"b": 1}
    assert report["source_quality"]["scrapers"]["manual_csv"]["success_percent"] == 100.0


# ------------------------------------------------------------------ Fase 7
@pytest.fixture
def client(engine, cycle_settings):
    from app.api import routes as api

    def db():
        with session_scope(engine) as s:
            yield s

    with session_scope(engine) as s:
        run_cycle(s, cycle_settings, notifier=FakeNotifier())
    api.app.dependency_overrides[api.db] = db
    api.app.dependency_overrides[api.settings_dep] = lambda: cycle_settings
    yield TestClient(api.app)
    api.app.dependency_overrides.clear()


def test_api_top_and_lists(client):
    top = client.get("/api/top").json()
    assert top["routes"][0]["currencies"] == ["CLP", "USD", "CLP"]
    assert client.get("/api/top?capital=5000000").json()["routes"][0]["initial_clp"] == 5_000_000
    assert client.get("/api/quotes").json()
    assert client.get("/api/houses").json()["discovered"] == 2
    opps = client.get("/api/opportunities").json()
    assert opps and opps[0]["status"] == "DETECTED"
    detail = client.get(f"/api/opportunities/{opps[0]['id']}").json()
    assert detail["verification_messages"][0]["text"].startswith("Hola")
    assert "opportunities" in client.get("/api/stats").json()
    assert "BotCasaCambio" in client.get("/").text


def test_api_status_change(client):
    opp_id = client.get("/api/opportunities").json()[0]["id"]
    r = client.post(f"/api/opportunities/{opp_id}/status", json={"status": "FAILED"})
    assert r.status_code == 400  # falta la razón
    r = client.post(f"/api/opportunities/{opp_id}/status", json={"status": "VERIFIED", "reason": "ok"})
    assert r.status_code == 200 and r.json()["status"] == "VERIFIED"


def test_api_token(client, cycle_settings):
    from app.api import routes as api

    api.app.dependency_overrides[api.settings_dep] = lambda: cycle_settings.model_copy(update={"dashboard_token": "s3"})
    assert client.get("/api/quotes").status_code == 401
    assert client.get("/api/quotes?token=s3").status_code == 200
    assert client.get("/api/quotes", headers={"X-Token": "s3"}).status_code == 200


# ------------------------------------------------------------- aviso de baja
def _set_prices(settings, rows: str):
    from pathlib import Path

    Path(settings.manual_quotes_file).write_text("exchange_house,currency,buy_rate,sell_rate\n" + rows, encoding="utf-8")


def test_drop_alert_when_profit_falls_10_percent(engine, cycle_settings):
    notifier = FakeNotifier()
    with session_scope(engine) as s:
        run_cycle(s, cycle_settings, notifier=notifier)  # +$31.579 → alerta normal
    assert len(notifier.sent) == 1

    _set_prices(cycle_settings, "a,USD,930,950\nb,USD,977,1000\n")  # +$28.421: baja 10%
    with session_scope(engine) as s:
        result = run_cycle(s, cycle_settings, notifier=notifier)
        assert result.drop_alerts
    assert notifier.sent[-1].startswith("⚠️ BAJÓ LA GANANCIA")
    assert "Avisada: +$31.579 CLP" in notifier.sent[-1] and "Ahora: +$28.421 CLP (-10%)" in notifier.sent[-1]
    assert "Ruta: CLP → USD → CLP" in notifier.sent[-1]
    assert len(notifier.sent) == 2

    with session_scope(engine) as s:
        run_cycle(s, cycle_settings, notifier=notifier)  # sin cambios: no se repite
    assert len(notifier.sent) == 2


def test_small_drop_is_not_alerted(engine, cycle_settings):
    notifier = FakeNotifier()
    with session_scope(engine) as s:
        run_cycle(s, cycle_settings, notifier=notifier)
    _set_prices(cycle_settings, "a,USD,930,950\nb,USD,979,1000\n")  # baja ~3%
    with session_scope(engine) as s:
        assert not run_cycle(s, cycle_settings, notifier=notifier).drop_alerts
    assert len(notifier.sent) == 1


def test_drop_alert_when_route_disappears_only_once(engine, cycle_settings):
    notifier = FakeNotifier()
    with session_scope(engine) as s:
        run_cycle(s, cycle_settings, notifier=notifier)
    from pathlib import Path

    # La casa b publica que ya no tiene USD: la operación sale del grafo.
    Path(cycle_settings.manual_quotes_file).write_text(
        "exchange_house,currency,buy_rate,sell_rate,availability\na,USD,930,950,\nb,USD,980,1000,false\n",
        encoding="utf-8")
    for _ in range(2):
        with session_scope(engine) as s:
            run_cycle(s, cycle_settings, notifier=notifier)
    assert len(notifier.sent) == 2
    assert "ya no está publicada" in notifier.sent[-1]


def test_drop_alert_disabled(engine, cycle_settings):
    notifier = FakeNotifier()
    settings = cycle_settings.model_copy(update={"alert_drop_percent": 0})
    with session_scope(engine) as s:
        run_cycle(s, settings, notifier=notifier)
    _set_prices(settings, "a,USD,930,950\nb,USD,960,1000\n")
    with session_scope(engine) as s:
        assert run_cycle(s, settings, notifier=notifier).drop_alerts == []
    assert len(notifier.sent) == 1


def test_old_published_price_is_used_with_warning():
    from datetime import timedelta

    from app.models.quote import utcnow

    old = utcnow() - timedelta(days=5)
    quotes = [NormalizedQuote("a", "USD", 930.0, 950.0, "test://", timestamp_source=old).validate(),
              NormalizedQuote("b", "USD", 980.0, 1000.0, "test://").validate()]
    best = find_best_routes(quotes, initial_amount=1_000_000, settings=Settings(_env_file=None, safety_margin_percent=0),
                            directory=directory())[0]
    assert round(best.net_profit_clp) == 31_579  # misma ganancia: la antigüedad no cambia el ranking
    assert best.confidence == "LOW"
    text = format_alert([best], directory(), 1_000_000)
    assert "📅 Casa A publicó su precio de USD hace 5 días: puede seguir igual, confírmalo." in text
