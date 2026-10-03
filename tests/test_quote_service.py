import json

from sqlalchemy import select

from app.database.models import BranchRow, CurrencyRow, QuoteRow, ScraperRunRow
from app.models.quote import NormalizedQuote
from app.scrapers.base import BaseScraper
from app.services.house_service import house_stats, sync_houses
from app.services.quote_service import collect_quotes, latest_quotes


class Static(BaseScraper):
    slug = "static"

    def __init__(self, settings, quotes):
        super().__init__(settings)
        self.quotes = quotes

    def scrape(self):
        return [NormalizedQuote(**q) for q in self.quotes]


class Broken(BaseScraper):
    slug = "broken"

    def scrape(self):
        raise RuntimeError("caída")


def mk(house, cur, buy, sell):
    return dict(exchange_house=house, currency=cur, buy_rate=buy, sell_rate=sell, source_url="test://")


def test_collect_persists_everything_and_isolates_failures(session, settings):
    quotes = [mk("a", "USD", 940, 970), mk("b", "USD", 942, 969), mk("c", "USD", 939, 971), mk("d", "USD", 1500, 1530),
              mk("a", "XAU", 1, 2)]
    report = collect_quotes(session, [Broken(settings), Static(settings, quotes)], settings)
    assert report.saved_quotes == 5
    assert [r.scraper for r in report.failed] == ["broken"]
    runs = session.scalars(select(ScraperRunRow)).all()
    assert {r.status for r in runs} == {"ERROR", "OK"}
    d = session.scalars(select(QuoteRow).where(QuoteRow.buy_rate == 1500)).one()
    assert d.is_anomalous and "ANOMALOUS_QUOTE" in d.flags
    assert session.get(CurrencyRow, "XAU") is not None  # divisas nuevas se registran solas


def test_history_is_kept_and_latest_is_last(session, settings):
    collect_quotes(session, [Static(settings, [mk("a", "USD", 940, 970)])], settings)
    collect_quotes(session, [Static(settings, [mk("a", "USD", 941, 972)])], settings)
    assert len(session.scalars(select(QuoteRow)).all()) == 2
    [latest] = latest_quotes(session)
    assert latest.buy_rate == 941


def test_sync_houses_and_stats(session, settings, tmp_path):
    path = tmp_path / "houses.json"
    path.write_text(json.dumps({"exchange_houses": [
        {"slug": "a", "name": "Casa A", "branches": [{"name": "Centro", "address": "Calle 1"}]},
        {"slug": "b", "name": "Casa B"},
    ]}), encoding="utf-8")
    assert sync_houses(session, path) == 2
    assert sync_houses(session, path) == 2  # idempotente
    assert len(session.scalars(select(BranchRow)).all()) == 1
    collect_quotes(session, [Static(settings, [mk("a", "USD", 940, 970)])], settings)
    stats = house_stats(session, max_age_minutes=10)
    assert (stats.discovered, stats.with_active_quotes, stats.unavailable) == (2, 1, 1)


def test_repo_houses_file_loads(session):
    from app.config.settings import DATA_DIR

    assert sync_houses(session, DATA_DIR / "exchange_houses.json") >= 1
