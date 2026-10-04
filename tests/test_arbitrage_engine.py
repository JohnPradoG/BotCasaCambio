"""Tests del motor (SPEC §49). Todas las cotizaciones son sintéticas."""

import pytest

from app.config.settings import Settings
from app.models.quote import NormalizedQuote, QuoteFlag
from app.services.arbitrage_engine import (
    SearchStats,
    build_graph,
    find_best_routes,
    rank_routes,
    search_routes,
    sensitivity,
)

CAPITAL = 1_000_000


def q(house, cur, buy, sell, quote_currency="CLP", **kw):
    return NormalizedQuote(
        exchange_house=house, currency=cur, buy_rate=buy, sell_rate=sell,
        quote_currency=quote_currency, source_url="test://", **kw,
    ).validate()


def cfg(**kw):
    base = dict(_env_file=None, safety_margin_percent=0, max_steps=5, top_routes=3, search_beam_width=100)
    base.update(kw)
    return Settings(**base)


def best(quotes, **kw):
    settings = cfg(**{k: v for k, v in kw.items() if k in Settings.model_fields})
    extra = {k: v for k, v in kw.items() if k not in Settings.model_fields}
    return find_best_routes(quotes, initial_amount=CAPITAL, settings=settings, **extra)


def test_1_round_trip_with_loss_is_discarded():
    quotes = [q("a", "USD", 940, 970), q("b", "USD", 945, 965)]
    assert best(quotes) == []


def test_2_round_trip_with_profit_is_detected():
    # A vende USD a 950; B compra USD a 980.
    quotes = [q("a", "USD", 930, 950), q("b", "USD", 980, 1000)]
    [route] = best(quotes)
    assert route.currencies == ["CLP", "USD", "CLP"]
    assert route.houses == ["a", "b"]
    assert route.final_clp == pytest.approx(CAPITAL / 950 * 980)
    assert route.net_profit_clp == pytest.approx(CAPITAL / 950 * 980 - CAPITAL)
    # Compra/venta correctas: CLP→USD usa la VENTA de la casa, USD→CLP su COMPRA.
    assert [s.rate_used for s in route.route] == ["sell_rate", "buy_rate"]


def test_3_clp_usd_eur_clp_is_computed_exactly():
    quotes = [
        q("a", "USD", 930, 950),
        q("b", "EUR", 1.00, 1.05, quote_currency="USD"),  # B cotiza EUR en USD
        q("c", "EUR", 1100, 1150),
    ]
    routes = best(quotes)
    route = next(r for r in routes if r.currencies == ["CLP", "USD", "EUR", "CLP"])
    expected = CAPITAL / 950 / 1.05 * 1100
    assert route.final_clp == pytest.approx(expected)
    assert route.route[1].amount_out == pytest.approx(CAPITAL / 950 / 1.05)
    assert route.houses == ["a", "b", "c"]


def test_4_clp_as_intermediate_node_is_allowed_and_wins():
    quotes = [
        q("a", "USD", 930, 950), q("b", "USD", 980, 1000),  # loop USD: +3,16%
        q("c", "EUR", 1000, 1020), q("d", "EUR", 1050, 1080),  # loop EUR: +2,94%
    ]
    routes = best(quotes)
    top = routes[0]
    assert top.steps == 4
    assert top.currencies[2] == "CLP" and top.currencies[0] == top.currencies[-1] == "CLP"
    assert set(top.currencies) == {"CLP", "USD", "EUR"}
    assert top.final_clp == pytest.approx(CAPITAL * (980 / 950) * (1050 / 1020))
    # Ganancia > cualquiera de los dos loops por separado.
    assert top.net_profit_clp > max(r.net_profit_clp for r in routes[1:])


def test_ranking_is_by_net_profit_not_percent_or_steps():
    quotes = [
        q("a", "USD", 930, 950), q("b", "USD", 980, 1000),
        q("c", "EUR", 1000, 1020), q("d", "EUR", 1050, 1080),
    ]
    routes = best(quotes, top_routes=10)
    profits = [r.net_profit_clp for r in routes]
    assert profits == sorted(profits, reverse=True)
    assert [r.rank for r in routes] == list(range(1, len(routes) + 1))


def test_8_commission_is_deducted():
    plain = best([q("a", "USD", 930, 950), q("b", "USD", 980, 1000)])[0]
    with_fee = best([q("a", "USD", 930, 950, commission_percent=1.0), q("b", "USD", 980, 1000, commission_fixed=2000)])[0]
    expected = (CAPITAL / 950) * 0.99 * 980 - 2000
    assert with_fee.final_clp == pytest.approx(plain.final_clp)  # bruto sin comisiones
    assert with_fee.net_final_clp == pytest.approx(expected)
    assert with_fee.commissions_clp == pytest.approx(plain.final_clp - expected)
    assert with_fee.net_profit_clp < plain.net_profit_clp


def test_unknown_commission_is_flagged_and_manual_estimate_used():
    quotes = [q("a", "USD", 930, 950), q("b", "USD", 980, 1000)]
    [route] = best(quotes)
    assert "COMMISSION_UNKNOWN" in route.flags
    [est] = best(quotes, default_commission_percent=0.5)
    assert "COMMISSION_ESTIMATED" in est.flags
    assert est.net_profit_clp == pytest.approx(CAPITAL / 950 * 0.995 * 980 * 0.995 - CAPITAL)


def test_safety_margin_reduces_net_profit():
    quotes = [q("a", "USD", 930, 950), q("b", "USD", 980, 1000)]
    [route] = best(quotes, safety_margin_percent=0.5)
    expected_net = CAPITAL / (950 * 1.005) * 980 * 0.995
    assert route.net_final_clp == pytest.approx(expected_net)
    assert route.safety_margin_clp == pytest.approx(route.final_clp - expected_net)
    assert route.gross_profit_clp > route.net_profit_clp


def test_safety_margin_can_remove_thin_opportunity():
    quotes = [q("a", "USD", 930, 950), q("b", "USD", 952, 1000)]  # +0,21% bruto
    assert len(best(quotes)) == 1
    assert best(quotes, safety_margin_percent=0.5) == []


def test_10_two_similar_routes_both_appear():
    quotes = [
        q("a", "USD", 930, 950), q("b", "USD", 980, 1000),
        q("c", "USD", 979.9, 1000),  # casi igual que b
    ]
    routes = best(quotes, max_steps=2)
    sigs = {tuple(r.houses) for r in routes}
    assert {("a", "b"), ("a", "c")} <= sigs


def test_11_infinite_cycle_is_blocked():
    # Inverted spread en la misma casa: un ciclo "gratis" que se repetiría siempre.
    quotes = [q("a", "USD", 1000, 950)]
    stats = SearchStats()
    routes = best(quotes, max_steps=50, stats=stats)
    assert all(r.steps <= 2 for r in routes)  # la operación no se repite
    assert len(routes) == 1
    assert stats.expanded < 10


def test_losing_loop_cannot_be_used_inside_longer_route():
    quotes = [
        q("a", "USD", 940, 970), q("b", "USD", 945, 965),  # USD: solo pérdidas
        q("c", "EUR", 1000, 1020), q("d", "EUR", 1050, 1080),  # EUR: ganancia
    ]
    routes = best(quotes, top_routes=20)
    assert routes and all("USD" not in r.currencies for r in routes)


def test_permutations_of_same_operations_are_one_route():
    quotes = [
        q("a", "USD", 930, 950), q("b", "USD", 980, 1000),
        q("c", "EUR", 1000, 1020), q("d", "EUR", 1050, 1080),
    ]
    routes = best(quotes, top_routes=50)
    four_step = [r for r in routes if r.steps == 4]
    assert len(four_step) == 1


def test_max_steps_is_respected():
    quotes = [
        q("a", "USD", 930, 950), q("b", "USD", 980, 1000),
        q("c", "EUR", 1000, 1020), q("d", "EUR", 1050, 1080),
    ]
    assert all(r.steps <= 2 for r in best(quotes, max_steps=2, top_routes=50))


def test_route_must_return_to_base_currency():
    quotes = [q("a", "USD", 930, 950)]
    assert best(quotes) == []


def test_capital_changes_recalculate():
    quotes = [q("a", "USD", 930, 950), q("b", "USD", 980, 1000, commission_fixed=5000)]
    settings = cfg()
    # Con 100.000 CLP la ganancia bruta (3.158) no cubre la comisión fija de 5.000.
    small = find_best_routes(quotes, initial_amount=100_000, settings=settings)
    large = find_best_routes(quotes, initial_amount=10_000_000, settings=settings)
    assert small == []
    assert large[0].net_profit_clp == pytest.approx(10_000_000 / 950 * 980 - 5000 - 10_000_000)


def test_anomalous_quote_marks_route_for_verification():
    quotes = [q("a", "USD", 930, 950), q("b", "USD", 1500, 1530)]
    quotes[1].flags.add(QuoteFlag.ANOMALOUS_QUOTE)
    [route] = best(quotes)
    assert route.requires_verification
    assert "ANOMALOUS_QUOTE" in route.flags


def test_sensitivity_simulation():
    quotes = [q("a", "USD", 930, 950), q("b", "USD", 980, 1000)]
    [route] = best(quotes)
    sens = sensitivity(route, (0.005, 0.01))
    assert sens[0.005] == pytest.approx(CAPITAL / (950 * 1.005) * 980 * 0.995 - CAPITAL)
    assert sens[0.01] < sens[0.005] < route.net_profit_clp


def test_output_shape_matches_spec_25():
    quotes = [q("a", "USD", 930, 950), q("b", "USD", 980, 1000)]
    data = best(quotes)[0].to_dict()
    for key in ("rank", "initial_clp", "final_clp", "gross_profit_clp", "net_profit_clp", "profit_percent",
                "steps", "distance_km", "estimated_minutes", "confidence", "route", "quotes", "houses"):
        assert key in data


def test_many_houses_and_currencies_stay_fast():
    import random
    import time

    rng = random.Random(1)
    quotes = []
    for h in range(20):
        for cur, mid in [("USD", 950), ("EUR", 1030), ("GBP", 1200), ("BRL", 170), ("ARS", 0.9),
                         ("PEN", 250), ("CAD", 690), ("AUD", 620), ("JPY", 6.4), ("CHF", 1080)]:
            m = mid * rng.uniform(0.98, 1.02)
            quotes.append(q(f"h{h}", cur, round(m * 0.985, 4), round(m * 1.015, 4)))
    start = time.perf_counter()
    routes = find_best_routes(quotes, initial_amount=CAPITAL, settings=cfg(search_beam_width=50))
    assert time.perf_counter() - start < 20
    profits = [r.net_profit_clp for r in routes]
    assert profits == sorted(profits, reverse=True)


def test_graph_edges_use_correct_rates():
    graph = build_graph([q("a", "USD", 940, 970)])
    [buy_usd] = graph.edges["CLP"]
    [sell_usd] = graph.edges["USD"]
    assert (buy_usd.to_currency, buy_usd.rate, buy_usd.side) == ("USD", 970, "sell")
    assert (sell_usd.to_currency, sell_usd.rate, sell_usd.side) == ("CLP", 940, "buy")
    assert buy_usd.convert(970_000) == pytest.approx(1000)
    assert sell_usd.convert(1000) == pytest.approx(940_000)


def test_rank_routes_assigns_ranks():
    graph = build_graph([q("a", "USD", 930, 950), q("b", "USD", 980, 1000), q("c", "USD", 970, 1000)])
    routes = rank_routes(search_routes(graph, initial_amount=CAPITAL, max_steps=2), top_n=1)
    assert len(routes) == 1 and routes[0].rank == 1 and routes[0].houses == ["a", "b"]


def test_beam_finds_same_best_as_exhaustive_search():
    import random

    rng = random.Random(7)
    quotes = []
    for h in range(6):
        for cur, mid in [("USD", 950), ("EUR", 1030), ("BRL", 170), ("PEN", 250)]:
            m = mid * rng.uniform(0.97, 1.03)
            quotes.append(q(f"h{h}", cur, round(m * 0.99, 4), round(m * 1.01, 4)))
    narrow = find_best_routes(quotes, initial_amount=CAPITAL, max_steps=4, settings=cfg(search_beam_width=20))
    wide = find_best_routes(quotes, initial_amount=CAPITAL, max_steps=4, settings=cfg(search_beam_width=100_000))
    assert wide, "el escenario debería tener oportunidades"
    assert [round(r.net_profit_clp, 6) for r in narrow] == [round(r.net_profit_clp, 6) for r in wide]
