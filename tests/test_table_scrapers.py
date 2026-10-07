"""Scrapers de tabla HTML (Gamaex, Cambios Lyon, Inmonex) con fixtures reconstruidos."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.scrapers.base import ScraperStatus
from app.scrapers.exchanges.cambios_lyon import CambiosLyonScraper
from app.scrapers.exchanges.gamaex import GamaexScraper
from app.scrapers.exchanges.inmonex import InmonexScraper
from app.scrapers.table_scraper import parse_spanish_update_time, says_no_commission

FIXTURES = Path(__file__).parent / "fixtures"


def by_currency(quotes):
    return {q.currency: q for q in quotes}


def test_gamaex_client_labels_are_inverted(settings):
    q = by_currency(GamaexScraper(settings).parse((FIXTURES / "gamaex.html").read_text(encoding="utf-8")))
    # "Vendes" (el cliente vende) = la casa compra; "Compras" (el cliente compra) = la casa vende.
    assert (q["USD"].buy_rate, q["USD"].sell_rate) == (976, 989)
    assert (q["EUR"].buy_rate, q["EUR"].sell_rate) == (1097, 1123)
    assert (q["ARS"].buy_rate, q["ARS"].sell_rate) == (0.611, 0.639)
    assert (q["JPY"].buy_rate, q["JPY"].sell_rate) == (6.21, 6.69)
    assert "PYG" in q and "ORO" not in q and len(q) == 7  # el oro no es una divisa ISO
    assert q["USD"].commission_percent == 0 and q["USD"].commission_fixed == 0  # "Sin comisiones"
    assert not q["USD"].commission_unknown
    assert q["USD"].source_url == "https://www.gamaex.cl/"


def test_cambios_lyon_reads_update_time_and_missing_sell(settings):
    q = by_currency(CambiosLyonScraper(settings).parse((FIXTURES / "cambios_lyon.html").read_text(encoding="utf-8")))
    assert (q["USD"].buy_rate, q["USD"].sell_rate) == (970, 995)
    assert (q["ARS"].buy_rate, q["ARS"].sell_rate) == (0.55, 0.72)
    assert q["GBP"].sell_rate is None and q["GBP"].buy_rate == 1120  # venta no publicada: None
    assert q["JPY"].buy_rate == 5.5 and q["PEN"].sell_rate == 280 and q["NZD"].buy_rate == 520
    # 10:00 en Santiago (UTC-3 en octubre, horario de verano) = 13:00 UTC
    assert q["USD"].timestamp_source == datetime(2026, 10, 2, 13, 0, tzinfo=timezone.utc)
    assert q["USD"].commission_unknown  # Lyon no publica comisión


def test_inmonex_mixed_decimal_formats(settings):
    q = by_currency(InmonexScraper(settings).parse((FIXTURES / "inmonex.html").read_text(encoding="utf-8")))
    assert (q["USD"].buy_rate, q["USD"].sell_rate) == (970, 990)
    assert (q["EUR"].buy_rate, q["EUR"].sell_rate) == (1100, 1125)
    assert (q["ARS"].buy_rate, q["ARS"].sell_rate) == (0.60, 0.65)
    assert (q["COP"].buy_rate, q["COP"].sell_rate) == (0.28, 0.33)
    assert q["BRL"].timestamp_source is None and q["BRL"].commission_unknown


def test_table_scraper_reports_structure_change(settings):
    class Resp:
        status_code = 200
        text = "<html><body><p>Página en mantención</p></body></html>"

        def raise_for_status(self):
            pass

    class Sess:
        headers = {}

        def get(self, url, **kw):
            return Resp()

    s = settings.model_copy(update={"respect_robots_txt": False})
    result = InmonexScraper(s, session=Sess()).run()
    assert result.status is ScraperStatus.STRUCTURE_CHANGED and not result.quotes


@pytest.mark.parametrize("text,expected", [
    ("Última actualización 02 de Octubre de 2026 , 10:00 Horas", datetime(2026, 10, 2, 13, 0, tzinfo=timezone.utc)),
    ("Ultima actualizacion: 15 de enero 2026, 9:30", datetime(2026, 1, 15, 12, 30, tzinfo=timezone.utc)),
    ("Actualizado hoy", None),
    ("Última actualización 31 de febrero de 2026, 10:00", None),
])
def test_parse_spanish_update_time(text, expected):
    assert parse_spanish_update_time(text) == expected


def test_says_no_commission():
    assert says_no_commission("Cotización referencial · Sin comisiones · Atención inmediata")
    assert says_no_commission("0% comisiones")
    assert not says_no_commission("Comisión 1% sobre el monto")
    assert not says_no_commission("Sin comisiones ocultas")


def test_brollano_branch_quotes_and_unlabeled_date(settings):
    from app.scrapers.exchanges.brollano import PAGES, BrollanoScraper

    scraper = BrollanoScraper(settings)
    prov = by_currency(scraper.parse((FIXTURES / "brollano_providencia.html").read_text(encoding="utf-8"),
                                     url=PAGES[0][0], branch="Providencia"))
    agus = by_currency(scraper.parse((FIXTURES / "brollano_agustinas.html").read_text(encoding="utf-8"),
                                     url=PAGES[1][0], branch="Agustinas"))
    assert (prov["USD"].buy_rate, prov["USD"].sell_rate, prov["USD"].branch) == (972, 990, "Providencia")
    assert prov["ARS"].buy_rate == 0.6 and prov["UYU"].buy_rate is None and prov["UYU"].sell_rate == 30
    assert "DKK" not in prov and "NZD" in prov  # "–"/"—" = sin precio; el oro no es divisa
    assert prov["USD"].timestamp_source == datetime(2026, 10, 1, 14, 0, tzinfo=timezone.utc)
    assert (agus["EUR"].buy_rate, agus["EUR"].sell_rate) == (1078, 1092) and agus["BOB"].sell_rate == 86
    assert agus["USD"].timestamp_source == datetime(2026, 9, 2, 19, 0, tzinfo=timezone.utc)  # aún UTC-4
    assert agus["USD"].source_url.endswith("precios-agustinas/") and "SEK" not in agus


def test_cambio_costero_is_sell_only(settings):
    from app.scrapers.exchanges.cambio_costero import CambioCosteroScraper

    q = by_currency(CambioCosteroScraper(settings).parse((FIXTURES / "cambio_costero.html").read_text(encoding="utf-8")))
    assert set(q) == {"USD", "EUR", "ARS", "BRL", "JPY"}
    assert (q["USD"].buy_rate, q["USD"].sell_rate) == (None, 988)
    assert q["EUR"].sell_rate == 1130 and q["ARS"].sell_rate == 0.66 and q["JPY"].sell_rate == 6.9


def test_cambio_costero_reads_wcps_carousel(settings):
    """HTML real (recortado): los precios vienen en carruseles .wcps-items, no en li.product."""
    from app.scrapers.exchanges.cambio_costero import CambioCosteroScraper

    html = (FIXTURES / "cambio_costero_wcps.html").read_text(encoding="utf-8")
    q = by_currency(CambioCosteroScraper(settings).parse(html))
    assert len(q) == 17 and "ORO" not in q  # 18 productos, uno es la moneda de oro
    # el número sin etiqueta es la compra (confirmado por John 2026-10-07)
    assert (q["USD"].buy_rate, q["USD"].sell_rate) == (970, 988)
    assert (q["EUR"].buy_rate, q["ARS"].buy_rate, q["BRL"].buy_rate, q["CAD"].buy_rate) == (1110, 0.61, 185, 640)
    assert q["EUR"].sell_rate == 1130 and q["COP"].sell_rate == 0.35 and q["NZD"].sell_rate == 543
    assert q["COP"].buy_rate is None  # sin número en el carrusel: la compra no se conoce


def test_quote_with_old_published_time_is_not_used(engine, settings):
    from datetime import timedelta

    from app.database.db import session_scope
    from app.models.quote import NormalizedQuote, utcnow
    from app.services.opportunity_service import quotes_for_engine
    from app.services.quote_service import save_quote

    now = utcnow()
    with session_scope(engine) as s:
        for house, ts in (("old", now - timedelta(days=31)), ("days", now - timedelta(days=5)),
                          ("new", now - timedelta(hours=2))):
            save_quote(s, NormalizedQuote(house, "USD", 970, 990, "test://", timestamp_source=ts).validate(), None)
        assert [q.exchange_house for q in quotes_for_engine(s, 24 * 60)] == ["new"]
        # precios publicados hace unos días se usan (pueden no haber cambiado); hace un mes, no
        assert sorted(q.exchange_house for q in quotes_for_engine(s, 24 * 60, 14 * 1440)) == ["days", "new"]
        assert len(quotes_for_engine(s, None)) == 3  # sin límite, se ve todo el historial


class _Resp:
    def __init__(self, text, status=200):
        self.text, self.status_code = text, status

    def raise_for_status(self):
        pass


class _Sess:
    headers: dict = {}

    def __init__(self, pages):
        self.pages = pages

    def get(self, url, **kw):
        return _Resp(self.pages[url])


def test_rendered_scraper_uses_static_table_when_present(settings):
    from app.scrapers.exchanges.cambios_santiago import CambiosSantiagoScraper

    html = ("<table><tr><th>DIVISA</th><th>COMPRAMOS</th><th>VENDEMOS</th></tr>"
            "<tr><td>Dólar</td><td>970</td><td>990</td></tr></table>")
    s = settings.model_copy(update={"respect_robots_txt": False})
    [q] = CambiosSantiagoScraper(s, session=_Sess({"https://cstgo.cl/": html})).run().quotes
    assert (q.currency, q.buy_rate, q.sell_rate, q.branch) == ("USD", 970, 990, "Providencia")


def test_rendered_scraper_without_playwright_reports_structure_change(settings, monkeypatch):
    import builtins

    from app.scrapers.exchanges.cambios_santiago import CambiosSantiagoScraper

    real_import = builtins.__import__

    def no_playwright(name, *a, **kw):
        if name.startswith("playwright"):
            raise ImportError("sin playwright")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", no_playwright)
    empty = "<table><tr><th>DIVISA</th><th>COMPRAMOS</th><th>VENDEMOS</th></tr></table>"
    s = settings.model_copy(update={"respect_robots_txt": False})
    result = CambiosSantiagoScraper(s, session=_Sess({"https://cstgo.cl/": empty})).run()
    assert result.status is ScraperStatus.STRUCTURE_CHANGED and "Playwright" in result.error


def test_probe_site_finds_static_rates_and_errors(settings):
    from app.services.probe_service import _Fetcher, probe_site

    s = settings.model_copy(update={"respect_robots_txt": False})
    html = (FIXTURES / "inmonex.html").read_text(encoding="utf-8")
    ok = probe_site("https://x.cl/", s, use_browser=False, fetcher=_Fetcher(s, session=_Sess({"https://x.cl/": html})))
    assert ok["static_rates"] == 5 and ok["static_sample"][0].startswith("USD")
    no_scheme = probe_site("x.cl/", s, use_browser=False, fetcher=_Fetcher(s, session=_Sess({"https://x.cl/": html})))
    assert no_scheme["url"] == "https://x.cl/" and "error" not in no_scheme
    bad = probe_site("https://y.cl/", s, use_browser=False, fetcher=_Fetcher(s, session=_Sess({})))
    assert "error" in bad
