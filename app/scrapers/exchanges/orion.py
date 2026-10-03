"""Cambios Orion (https://cambiosorion.cl/divisas): tabla Divisa | Compra | Venta cargada con JavaScript.

El HTML estático trae la tabla vacía ("Actualizado: --"); el scraper la lee con
navegador (Playwright). Casa en Agustinas 1035, Of. 13 (Santiago Centro).

Estado: NO VERIFICADO. Probar con ``python -m app.main probe-all``.
"""

from app.scrapers.registry import register
from app.scrapers.table_scraper import RenderedTableScraper


@register
class OrionScraper(RenderedTableScraper):
    slug = "orion"
    house_slug = "orion"
    source_url = "https://cambiosorion.cl/divisas"
    verified = False
    # La página muestra "Actualizado: --" sin cargar; falta ver su formato real antes de leer la hora.
