"""Inmonex (https://inmonex.cl): tabla HTML estática en la portada.

La página no publica hora de actualización y dice "visita nuestra sucursal y
negociamos la tasa del día": son precios de referencia.

Estado: estructura leída el 2026-10-03 a través de una conversión a texto de la
página; no se pudo descargar el HTML original desde el entorno de desarrollo.
Probar con ``python -m app.main scrape --only inmonex`` antes de marcarlo verificado.
"""

from app.scrapers.registry import register
from app.scrapers.table_scraper import HtmlTableScraper


@register
class InmonexScraper(HtmlTableScraper):
    slug = "inmonex"
    house_slug = "inmonex"
    source_url = "https://inmonex.cl/"
    verified = False
    notes = "precio de referencia publicado; la casa negocia la tasa del día en sucursal"
