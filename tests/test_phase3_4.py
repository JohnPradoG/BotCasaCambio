"""Fases 3 y 4: disponibilidad, montos, cotizaciones antiguas, horarios, distancia, transporte y confianza.

Casas, coordenadas y precios son sintéticos (solo para tests).
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.config.settings import Settings
from app.models.exchange_house import Branch, ExchangeHouse
from app.models.quote import NormalizedQuote
from app.services.arbitrage_engine import find_best_routes
from app.services.distance_service import StraightLineProvider, haversine_km
from app.services.schedule_service import is_open

CAPITAL = 1_000_000
# Lunes 2026-10-05 12:00 en Santiago (UTC-3 en octubre).
NOW = datetime(2026, 10, 5, 15, 0, tzinfo=timezone.utc)
ALL_WEEK = {d: ["09:00", "19:00"] for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}


def q(house, cur, buy, sell, age_min=1, **kw):
    return NormalizedQuote(
        exchange_house=house, currency=cur, buy_rate=buy, sell_rate=sell, source_url="test://",
        timestamp_collected=NOW - timedelta(minutes=age_min), **kw,
    ).validate()


def house(slug, lat=None, lon=None, schedule=ALL_WEEK):
    return ExchangeHouse(slug=slug, name=slug.upper(), branches=[
        Branch(name="Centro", address="(sintética)", latitude=lat, longitude=lon, schedule=schedule)
    ])


def cfg(**kw):
    base = dict(_env_file=None, safety_margin_percent=0, transport_cost_per_km=0, top_routes=3)
    base.update(kw)
    return Settings(**base)


def run(quotes, directory=None, **kw):
    settings = cfg(**kw)
    return find_best_routes(quotes, initial_amount=CAPITAL, settings=settings, directory=directory or {}, now=NOW,
                            distance_provider=StraightLineProvider("public_transport", 1.3))


# ------------------------------------------------------------------ Fase 3
def test_unavailable_currency_is_not_used():
    quotes = [q("a", "USD", 930, 950), q("b", "USD", 980, 1000, availability=False)]
    assert run(quotes) == []


def test_max_amount_blocks_rate_for_full_capital():
    # B compra USD a 980 pero solo hasta 500 USD; con 1.000.000 CLP tendríamos ~1.052 USD.
    quotes = [q("a", "USD", 930, 950), q("b", "USD", 980, 1000, max_amount=500)]
    assert run(quotes) == []
    small = find_best_routes(quotes, initial_amount=400_000, settings=cfg(), now=NOW)
    assert len(small) == 1


def test_min_amount_is_respected():
    quotes = [q("a", "USD", 930, 950, min_amount=5000), q("b", "USD", 980, 1000)]
    assert run(quotes) == []


def test_6_stale_quote_reduces_confidence():
    fresh = run([q("a", "USD", 930, 950), q("b", "USD", 980, 1000)])[0]
    stale = run([q("a", "USD", 930, 950, age_min=45), q("b", "USD", 980, 1000)])[0]
    assert "STALE_QUOTE" in stale.flags and "STALE_QUOTE" not in fresh.flags
    assert stale.confidence_score < fresh.confidence_score
    assert stale.confidence != "HIGH"
    assert stale.net_profit_clp == pytest.approx(fresh.net_profit_clp)  # no altera la ganancia


def test_6b_published_time_counts_for_quote_age():
    # Leída hace 1 minuto, pero la casa dice que la actualizó hace 3 horas.
    old = run([q("a", "USD", 930, 950, timestamp_source=NOW - timedelta(hours=3)), q("b", "USD", 980, 1000)])[0]
    assert "STALE_QUOTE" in old.flags
    assert max(s.quote_age_minutes for s in old.route) == pytest.approx(180)
    fresh = run([q("a", "USD", 930, 950), q("b", "USD", 980, 1000)])[0]
    assert old.net_profit_clp == pytest.approx(fresh.net_profit_clp) and old.rank == 1


def test_7_closed_house_is_not_executable_now():
    closed = {d: None for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}
    directory = {"a": house("a", -33.44, -70.65), "b": house("b", -33.45, -70.66, schedule=closed)}
    [route] = run([q("a", "USD", 930, 950), q("b", "USD", 980, 1000)], directory)
    assert route.executable_now is False
    assert "HOUSE_CLOSED" in route.flags
    assert route.rank == 1  # sigue guardada/mostrada como oportunidad futura


def test_open_houses_are_executable_and_unknown_hours_are_unknown():
    directory = {"a": house("a", -33.44, -70.65), "b": house("b", -33.45, -70.66)}
    [route] = run([q("a", "USD", 930, 950), q("b", "USD", 980, 1000)], directory)
    assert route.executable_now is True
    directory["b"] = house("b", -33.45, -70.66, schedule=None)
    [route] = run([q("a", "USD", 930, 950), q("b", "USD", 980, 1000)], directory)
    assert route.executable_now is None and "HOURS_UNKNOWN" in route.flags


def test_schedule_parsing():
    monday_noon = datetime(2026, 10, 5, 15, 0, tzinfo=timezone.utc)  # 12:00 Santiago
    assert is_open({"mon": ["09:00", "18:00"]}, monday_noon) is True
    assert is_open({"mon": [["09:00", "11:00"], ["14:00", "18:00"]]}, monday_noon) is False
    assert is_open({"mon": None}, monday_noon) is False
    assert is_open({"tue": ["09:00", "18:00"]}, monday_noon) is None
    assert is_open(None, monday_noon) is None


# ------------------------------------------------------------------ Fase 4
def test_5_more_profitable_but_farther_route_stays_first():
    directory = {
        "a": house("a", -33.4372, -70.6506),
        "far": house("far", -33.5200, -70.5800),  # ~11 km
        "near": house("near", -33.4380, -70.6510),  # ~100 m
    }
    quotes = [q("a", "USD", 930, 950), q("far", "USD", 990, 1010), q("near", "USD", 975, 1000)]
    routes = run(quotes, directory, max_steps=2)
    assert routes[0].houses == ["a", "far"]
    assert routes[1].houses == ["a", "near"]
    assert routes[0].distance_km > routes[1].distance_km
    assert routes[0].estimated_minutes > routes[1].estimated_minutes
    assert routes[0].confidence_score < routes[1].confidence_score  # más riesgo, mismo puesto


def test_9_transport_cost_is_deducted_from_net_profit():
    directory = {"a": house("a", -33.4372, -70.6506), "b": house("b", -33.4500, -70.6600)}
    quotes = [q("a", "USD", 930, 950), q("b", "USD", 980, 1000)]
    free = run(quotes, directory)[0]
    paid = run(quotes, directory, transport_cost_per_km=500, transport_fixed_cost_per_trip_clp=800)[0]
    expected = paid.distance_km * 500 + 800
    assert paid.transport_clp == pytest.approx(expected, rel=1e-3)
    assert paid.net_profit_clp == pytest.approx(free.net_profit_clp - paid.transport_clp)
    assert paid.gross_profit_clp == pytest.approx(free.gross_profit_clp)


def test_transport_can_change_the_order():
    directory = {
        "a": house("a", -33.4372, -70.6506),
        "far": house("far", -33.5200, -70.5800),
        "near": house("near", -33.4380, -70.6510),
    }
    quotes = [q("a", "USD", 930, 950), q("far", "USD", 982, 1010), q("near", "USD", 980, 1000)]
    routes = run(quotes, directory, max_steps=2, transport_cost_per_km=1000)
    # "far" paga ~2.100 CLP más, pero el traslado de ~14 km cuesta más que eso.
    assert routes[0].houses == ["a", "near"]


def test_missing_coordinates_mark_distance_unknown():
    [route] = run([q("a", "USD", 930, 950), q("b", "USD", 980, 1000)], {"a": house("a"), "b": house("b")})
    assert route.distance_km is None and "DISTANCE_UNKNOWN" in route.flags


def test_same_house_consecutive_steps_need_no_travel():
    directory = {"a": house("a", -33.44, -70.65), "b": house("b", -33.45, -70.66)}
    quotes = [q("a", "USD", 930, 950), q("b", "USD", 980, 1000), q("b", "EUR", 1050, 1060), q("a", "EUR", 1000, 1020)]
    routes = run(quotes, directory, top_routes=10)
    four = next(r for r in routes if r.steps == 4)
    assert len(four.legs) <= 3


def test_nearest_branch_is_chosen():
    a = ExchangeHouse(slug="a", name="A", branches=[
        Branch(name="Lejos", latitude=-33.60, longitude=-70.50, schedule=ALL_WEEK),
        Branch(name="Cerca", latitude=-33.451, longitude=-70.661, schedule=ALL_WEEK),
    ])
    directory = {"a": a, "b": house("b", -33.45, -70.66)}
    [route] = run([q("a", "USD", 930, 950), q("b", "USD", 980, 1000)], directory)
    assert route.route[0].branch_used == "Cerca"
    assert route.distance_km < 1


def test_haversine():
    # Plaza de Armas -> Plaza Italia, ~1,5 km en línea recta.
    assert haversine_km((-33.4378, -70.6504), (-33.4372, -70.6345)) == pytest.approx(1.47, abs=0.1)


def test_anomalous_route_confidence_is_low():
    quotes = [q("a", "USD", 930, 950), q("b", "USD", 1500, 1530)]
    from app.models.quote import QuoteFlag

    quotes[1].flags.add(QuoteFlag.ANOMALOUS_QUOTE)
    [route] = run(quotes)
    assert route.confidence == "LOW"
