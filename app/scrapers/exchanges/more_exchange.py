"""More Exchange (https://moreexchange.cl): tabla de precios cargada con JavaScript.

El HTML estático solo trae "Loading data..."; el scraper abre la página con un
navegador (Playwright) y lee la tabla ya cargada. El sitio indica que los precios
son de la Casa Central San Sebastián.

Estado: NO VERIFICADO. No se pudo ver la tabla cargada desde el entorno de
desarrollo. Probar con ``python -m app.main probe-all`` o
``python -m app.main scrape --only more_exchange``. Si la tabla está paginada,
puede que solo se lean las primeras divisas.
"""

from app.scrapers.registry import register
from app.scrapers.table_scraper import RenderedTableScraper


@register
class MoreExchangeScraper(RenderedTableScraper):
    slug = "more_exchange"
    house_slug = "more_exchange"
    source_url = "https://moreexchange.cl/"
    verified = False
    branch = "Casa Central San Sebastián"
    notes = "precios publicados para la Casa Central San Sebastián"
