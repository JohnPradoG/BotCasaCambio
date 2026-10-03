"""Gamaex (https://www.gamaex.cl): tabla HTML estática.

Columnas publicadas desde el punto de vista del cliente: "Vendes · You sell"
(= la casa compra, ``buy_rate``) y "Compras · You buy" (= la casa vende,
``sell_rate``). La traducción la hace ``classify_rate_label``.

Estado: estructura leída el 2026-10-03 a través de una conversión a texto de la
página; no se pudo descargar el HTML original desde el entorno de desarrollo.
Probar con ``python -m app.main scrape --only gamaex`` antes de marcarlo verificado.
"""

from app.scrapers.registry import register
from app.scrapers.table_scraper import HtmlTableScraper


@register
class GamaexScraper(HtmlTableScraper):
    slug = "gamaex"
    house_slug = "gamaex"
    source_url = "https://www.gamaex.cl/"
    verified = False
    reads_no_commission = True  # la página publica "0% comisiones" / "Sin comisiones ocultas"
    notes = "cotización referencial publicada; confirmar por WhatsApp antes de ir"
