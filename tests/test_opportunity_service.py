from sqlalchemy import select

from app.database.models import OpportunityRow, RouteRow
from app.scrapers.exchanges.manual_csv import ManualCsvScraper
from app.services.arbitrage_engine import find_best_routes
from app.services.opportunity_service import quotes_for_engine, save_routes
from app.services.quote_service import collect_quotes


def test_scrape_analyze_and_save(session, settings, tmp_path):
    path = tmp_path / "manual.csv"
    path.write_text(
        "exchange_house,currency,buy_rate,sell_rate\n"
        "casa_a,USD,930,950\n"
        "casa_b,USD,980,1000\n",
        encoding="utf-8",
    )
    collect_quotes(session, [ManualCsvScraper(settings, path=path)], settings)
    quotes = quotes_for_engine(session)
    assert {q.quote_id for q in quotes} and all(q.quote_id for q in quotes)
    routes = find_best_routes(quotes, initial_amount=1_000_000, settings=settings.model_copy(update={"safety_margin_percent": 0}))
    assert routes[0].houses == ["casa_a", "casa_b"]
    save_routes(session, routes)
    save_routes(session, routes)  # la misma ruta se reutiliza, la oportunidad se registra de nuevo
    assert len(session.scalars(select(RouteRow)).all()) == 1
    opps = session.scalars(select(OpportunityRow)).all()
    assert len(opps) == 2 and opps[0].status == "DETECTED"
    assert opps[0].quote_ids == [s.quote_id for s in routes[0].route]
