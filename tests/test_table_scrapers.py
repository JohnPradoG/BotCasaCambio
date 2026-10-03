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
