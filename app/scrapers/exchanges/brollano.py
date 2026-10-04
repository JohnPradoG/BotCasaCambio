"""Cambios Brollano (https://brollano.cl): una página de precios por sucursal.

Cada página tiene la tabla ``MONEDA | COMPRA | VENTA`` y una fecha como
"01 Octubre de 2026 – 11:00 horas.", que se guarda como ``timestamp_source``.
Las cotizaciones quedan asociadas a su sucursal (``branch``). Las sucursales de
Vitacura y Las Condes no tienen página de precios.

Al 2026-10-03 la página de Agustinas mostraba precios del 02 de septiembre: por
eso importa la fecha publicada (una cotización vieja no se usa para detectar).

Estado: estructura leída el 2026-10-03 a través de una conversión a texto de las
páginas; falta probar con ``python -m app.main scrape --only brollano``.
"""

from app.models.quote import NormalizedQuote
from app.scrapers.base import StructureChangedError
from app.scrapers.registry import register
from app.scrapers.table_scraper import HtmlTableScraper

PAGES = [
    ("http://brollano.cl/index.php/precios/precios-providencia/", "Providencia"),
    ("http://brollano.cl/index.php/precios/precios-agustinas/", "Agustinas"),
]


@register
class BrollanoScraper(HtmlTableScraper):
    slug = "brollano"
    house_slug = "brollano"
    source_url = PAGES[0][0]
    verified = False
    reads_update_time = True
    update_time_requires_label = False  # la página solo dice "01 Octubre de 2026 – 11:00 horas."
    notes = "precios de referencia publicados por sucursal"

    def scrape(self) -> list[NormalizedQuote]:
        quotes: list[NormalizedQuote] = []
        errors: list[str] = []
        for url, branch in PAGES:
            try:
                quotes += self.parse(self.http_get(url).text, url=url, branch=branch)
            except Exception as exc:  # noqa: BLE001 - una sucursal caída no debe ocultar la otra
                self.log.warning("Brollano %s: %s", branch, exc)
                errors.append(f"{branch}: {exc}")
        if not quotes:
            raise StructureChangedError("; ".join(errors) or "sin cotizaciones")
        return quotes
