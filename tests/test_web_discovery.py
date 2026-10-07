"""Descubrimiento automático de precios en webs de casas sin scraper."""

import json

from app.models.quote import QuoteFlag
from app.scrapers.base import ScraperStatus
from app.scrapers.exchanges.web_discovery import WebDiscoveryScraper, price_links

TABLE = ("<table><tr><th>Moneda</th><th>Compra</th><th>Venta</th></tr>"
         "<tr><td>Dólar</td><td>965</td><td>985</td></tr><tr><td>Euro</td><td>1.090</td><td>1.120</td></tr></table>")


class Resp:
    def __init__(self, text):
        self.text, self.status_code = text, 200

    def raise_for_status(self):
        pass


class Sess:
    headers: dict = {}

    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def get(self, url, **kw):
        self.calls.append(url)
        if url not in self.pages:
            raise ConnectionError(f"sin respuesta: {url}")
        return Resp(self.pages[url])


def setup(tmp_path, settings):
    houses = {"exchange_houses": [
        {"slug": "con_tabla", "name": "Con Tabla", "website": "https://a.cl/", "source_url": "https://a.cl/", "branches": []},
        {"slug": "subpagina", "name": "Subpágina", "website": "https://b.cl/", "source_url": "https://b.cl/", "branches": []},
        {"slug": "caida", "name": "Caída", "website": "https://c.cl/", "source_url": "https://c.cl/", "branches": []},
        {"slug": "con_scraper", "name": "X", "website": "https://d.cl/", "scraper": "x", "source_url": "https://d.cl/", "branches": []},
    ]}
    path = tmp_path / "houses.json"
    path.write_text(json.dumps(houses), encoding="utf-8")
    return settings.model_copy(update={"houses_file": str(path), "respect_robots_txt": False,
                                       "discovery_use_browser": False, "scraper_retries": 0})


def test_discovers_prices_on_home_and_price_subpage(tmp_path, settings):
    s = setup(tmp_path, settings)
    sess = Sess({
        "https://a.cl/": TABLE,
        "https://b.cl/": '<a href="/nosotros">Nosotros</a> <a href="/index.php/precios/hoy/">Precios</a>',
        "https://b.cl/index.php/precios/hoy/": TABLE,
    })
    result = WebDiscoveryScraper(s, session=sess).run()
    assert result.status is ScraperStatus.OK
    got = {(q.exchange_house, q.currency): q for q in result.quotes}
    assert set(got) == {("con_tabla", "USD"), ("con_tabla", "EUR"), ("subpagina", "USD"), ("subpagina", "EUR")}
    assert got[("subpagina", "USD")].source_url == "https://b.cl/index.php/precios/hoy/"
    assert got[("con_tabla", "EUR")].buy_rate == 1090 and QuoteFlag.AUTO_DISCOVERED in got[("con_tabla", "EUR")].flags
    assert "https://d.cl/" not in sess.calls  # casas con scraper propio no se revisan aquí

    state = json.loads((tmp_path / "discovery_state.json").read_text())
    assert state["caida"]["found"] == 0 and "sin respuesta" in state["caida"]["error"]

    # Segundo ciclo: el sitio sin precios no se vuelve a pedir hasta DISCOVERY_RETRY_HOURS.
    sess2 = Sess({"https://a.cl/": TABLE, "https://b.cl/": "", "https://c.cl/": TABLE})
    WebDiscoveryScraper(s, session=sess2).run()
    assert "https://c.cl/" not in sess2.calls and "https://a.cl/" in sess2.calls


def test_discovered_quotes_require_verification():
    from app.models.quote import NormalizedQuote
    from app.services.arbitrage_engine import find_best_routes
    from app.config.settings import Settings

    quotes = [NormalizedQuote("a", "USD", 930, 950, "t://").validate(),
              NormalizedQuote("b", "USD", 980, 1000, "t://", flags={QuoteFlag.AUTO_DISCOVERED}).validate()]
    [route] = find_best_routes(quotes, settings=Settings(_env_file=None, safety_margin_percent=0))
    assert route.requires_verification and route.confidence != "HIGH"
    assert any("automáticamente" in w for w in route.warnings)


def test_price_links_same_site_only():
    html = ('<a href="https://otro.cl/precios">x</a><a href="/cotizaciones">Cotizaciones</a>'
            '<a href="/contacto">Contacto</a><a href="https://www.a.cl/valores-del-dia">hoy</a>')
    assert price_links(html, "https://a.cl/") == ["https://a.cl/cotizaciones", "https://www.a.cl/valores-del-dia"]


def test_site_that_had_prices_is_retried_every_cycle(tmp_path, settings):
    s = setup(tmp_path, settings)
    WebDiscoveryScraper(s, session=Sess({"https://a.cl/": TABLE})).run()
    # una caída pasajera: a.cl no responde
    WebDiscoveryScraper(s, session=Sess({})).run()
    state = json.loads((tmp_path / "discovery_state.json").read_text())
    assert state["con_tabla"]["found"] == 0 and state["con_tabla"]["last_found"]
    # el ciclo siguiente lo vuelve a pedir (no espera DISCOVERY_RETRY_HOURS) y lo lee
    sess = Sess({"https://a.cl/": TABLE})
    result = WebDiscoveryScraper(s, session=sess).run()
    assert "https://a.cl/" in sess.calls and "https://c.cl/" not in sess.calls
    assert {q.exchange_house for q in result.quotes} == {"con_tabla"}
