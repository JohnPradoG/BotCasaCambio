import requests

from app.models.quote import NormalizedQuote
from app.scrapers.base import BaseScraper, ScraperStatus, StructureChangedError
from app.scrapers.exchanges.afex import AfexScraper
from app.scrapers.exchanges.manual_csv import ManualCsvScraper
from app.scrapers.registry import available_scrapers, get_scrapers


class Boom(BaseScraper):
    slug = "boom"

    def scrape(self):
        raise RuntimeError("sitio caído")


class Changed(BaseScraper):
    slug = "changed"

    def scrape(self):
        raise StructureChangedError("tabla no encontrada")


class Mixed(BaseScraper):
    slug = "mixed"

    def scrape(self):
        return [
            NormalizedQuote("x", "USD", 940.0, 970.0, "test://"),
            NormalizedQuote("x", "EUR", None, None, "test://"),
        ]


def test_broken_scraper_does_not_raise(settings):
    result = Boom(settings).run()
    assert result.status is ScraperStatus.ERROR and "sitio caído" in result.error


def test_structure_change_detected(settings):
    assert Changed(settings).run().status is ScraperStatus.STRUCTURE_CHANGED


def test_invalid_rows_are_dropped(settings):
    result = Mixed(settings).run()
    assert result.status is ScraperStatus.PARTIAL
    assert [q.currency for q in result.quotes] == ["USD"]
    assert len(result.rejected) == 1


class FlakySession(requests.Session):
    def __init__(self, fails):
        super().__init__()
        self.fails, self.calls = fails, 0

    def get(self, url, **kw):
        self.calls += 1
        if self.calls <= self.fails:
            raise requests.ConnectionError("timeout simulado")
        resp = requests.Response()
        resp.status_code, resp._content = 200, b"ok"
        return resp


def test_http_get_retries(settings):
    sess = FlakySession(fails=1)
    scraper = Mixed(settings, session=sess)
    assert scraper.http_get("https://example.invalid/").text == "ok"
    assert sess.calls == 2


def test_http_get_gives_up(settings):
    sess = FlakySession(fails=10)
    result = AfexScraper(settings, session=sess, use_browser=False).run()
    assert result.status is ScraperStatus.ERROR
    assert sess.calls == settings.scraper_retries + 1


def test_afex_placeholder_page_is_structure_changed(settings):
    class Placeholder(FlakySession):
        def get(self, url, **kw):
            resp = super().get(url, **kw)
            resp._content = "<p>Dólar hoy en AFEX</p><p>Compra — · Venta —</p>".encode()
            return resp

    result = AfexScraper(settings, session=Placeholder(0), use_browser=False).run()
    assert result.status is ScraperStatus.STRUCTURE_CHANGED
    assert result.quotes == []  # nunca inventa precios


def test_manual_csv(settings, tmp_path):
    path = tmp_path / "manual.csv"
    path.write_text(
        "exchange_house,currency,buy_rate,sell_rate,source_url,availability,commission_percent\n"
        "casa_a,Dólar,940,970,tel:+56000000000,si,\n"
        "casa_b,EUR,\"1.010\",\"1.060\",,,0.5\n"
        "casa_c,???,1,2,,,\n",
        encoding="utf-8",
    )
    result = ManualCsvScraper(settings, path=path).run()
    assert result.ok
    by_house = {q.exchange_house: q for q in result.quotes}
    assert set(by_house) == {"casa_a", "casa_b"}
    assert by_house["casa_a"].currency == "USD" and by_house["casa_a"].availability is True
    assert by_house["casa_a"].commission_unknown is True
    assert by_house["casa_b"].buy_rate == 1010.0 and by_house["casa_b"].commission_percent == 0.5
    assert by_house["casa_b"].source_url.startswith("manual:")


def test_manual_csv_missing_or_empty_is_ok(settings, tmp_path):
    assert ManualCsvScraper(settings, path=tmp_path / "nope.csv").run().status is ScraperStatus.OK


def test_registry():
    assert {"manual_csv", "afex"} <= set(available_scrapers())
    assert [s.slug for s in get_scrapers(["afex"])] == ["afex"]
