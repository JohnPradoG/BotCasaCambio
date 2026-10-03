"""Cambios Lyon (https://cambioslyon.cl/w25/): tabla HTML estática.

Publica "Última actualización DD de <mes> de AAAA, HH:MM Horas", que se guarda
como ``timestamp_source``. Varias divisas solo tienen precio de compra (la casa
no publica venta): quedan con ``sell_rate = None``.

Estado: estructura leída el 2026-10-03 a través de una conversión a texto de la
página; no se pudo descargar el HTML original desde el entorno de desarrollo.
Probar con ``python -m app.main scrape --only cambios_lyon`` antes de marcarlo verificado.
"""

from app.scrapers.registry import register
from app.scrapers.table_scraper import HtmlTableScraper


@register
class CambiosLyonScraper(HtmlTableScraper):
    slug = "cambios_lyon"
    house_slug = "cambios_lyon"
    source_url = "https://cambioslyon.cl/w25/"
    verified = False
    reads_update_time = True
    notes = "valores referenciales publicados; stock y disponibilidad pueden variar"
