"""Cambios Santiago (https://cstgo.cl): tabla "VALORES EN TIEMPO REAL" cargada con JavaScript.

Columnas ``DIVISA | COMPRAMOS | VENDEMOS`` (punto de vista de la casa). El HTML
estático trae la tabla vacía; el scraper la lee con un navegador (Playwright).

Estado: NO VERIFICADO. Probar con ``python -m app.main probe-all`` o
``python -m app.main scrape --only cambios_santiago``.
"""

from app.scrapers.registry import register
from app.scrapers.table_scraper import RenderedTableScraper


@register
class CambiosSantiagoScraper(RenderedTableScraper):
    slug = "cambios_santiago"
    house_slug = "cambios_santiago"
    source_url = "https://cstgo.cl/"
    verified = False
    branch = "Providencia"
