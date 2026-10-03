"""Cambio Costero (https://www.ccostero.cl): tienda WooCommerce con un precio por divisa.

Ese precio es el de **venta** de la casa (lo que cobra al cliente que compra divisa):
el sitio dice "Si deseas vendernos tus divisas debes acudir directamente a nuestras
oficinas", así que el precio de compra no está publicado y queda en ``None``.
La página aclara que los precios son referenciales.

Estado: estructura leída el 2026-10-03 a través de una conversión a texto de la
página; falta probar con ``python -m app.main scrape --only cambio_costero``.
"""

from __future__ import annotations

from bs4 import BeautifulSoup

from app.models.currency import normalize_currency_code
from app.models.quote import NormalizedQuote
from app.scrapers.base import BaseScraper, StructureChangedError
from app.scrapers.normalization import RateParseError, parse_rate
from app.scrapers.registry import register


def parse_woocommerce_prices(html: str) -> dict[str, float]:
    """{divisa: precio} de un listado de productos WooCommerce (título + precio)."""
    soup = BeautifulSoup(html, "html.parser")
    prices: dict[str, float] = {}
    for product in soup.select("li.product, div.product, .products .product"):
        title = product.select_one(".woocommerce-loop-product__title, h2, h3") or product.find("a")
        price = product.select_one(".price ins .amount, .price .amount, .amount")
        if not title or not price:
            continue
        currency = normalize_currency_code(title.get_text(" ", strip=True))
        if not currency or currency == "CLP" or currency in prices:
            continue
        try:
            value = parse_rate(price.get_text(" ", strip=True), decimal_separator=",")
        except RateParseError:
            continue
        if value:
            prices[currency] = value
    return prices


@register
class CambioCosteroScraper(BaseScraper):
    slug = "cambio_costero"
    source_url = "https://www.ccostero.cl/"
    verified = False

    def scrape(self) -> list[NormalizedQuote]:
        return self.parse(self.http_get(self.source_url).text)

    def parse(self, html: str) -> list[NormalizedQuote]:
        prices = parse_woocommerce_prices(html)
        if not prices:
            raise StructureChangedError("no se encontraron productos con precio en ccostero.cl")
        return [
            NormalizedQuote(exchange_house="cambio_costero", currency=cur, buy_rate=None, sell_rate=value,
                            source_url=self.source_url,
                            notes="precio de venta referencial; la compra no se publica (solo en oficinas)")
            for cur, value in prices.items()
        ]
