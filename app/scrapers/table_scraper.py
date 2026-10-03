"""Base para casas que publican sus precios en una tabla HTML estática.

El scraper específico solo declara la casa, la URL y, si corresponde, cómo leer
la hora de actualización publicada. La lectura de la tabla y el significado de
las columnas (compra/venta, "Vendes"/"Compras") viven en ``extractors`` y
``normalization``, como en el resto del proyecto.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from app.models.currency import _strip_accents
from app.models.quote import NormalizedQuote
from app.scrapers.base import BaseScraper, StructureChangedError
from app.scrapers.extractors import RawRate, parse_html_rate_table

_MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7,
    "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}
_DATE_TIME = (
    r"(\d{1,2})\s+(?:de\s+)?([a-z]+)\s+(?:de\s+|del\s+)?(\d{4})\s*[,\-\u2013\u2014]?\s*"
    r"(?:a\s+las\s+)?(\d{1,2}):(\d{2})"
)
_UPDATED_RE = re.compile(r"actualizacion\s*:?\s*" + _DATE_TIME, re.IGNORECASE)
_ANY_DATE_RE = re.compile(_DATE_TIME, re.IGNORECASE)
# "Sin comisiones ocultas" no dice que la comisión sea cero, así que no cuenta.
_NO_COMMISSION_RE = re.compile(r"\b(sin comisiones(?!\s+ocultas)|0\s*%\s*(de\s+)?comision(es)?)\b", re.IGNORECASE)


def parse_spanish_update_time(text: str, tz: str = "America/Santiago", require_label: bool = True) -> datetime | None:
    """Lee "Última actualización 02 de Octubre de 2026, 10:00 Horas" y la devuelve en UTC.

    Con ``require_label=False`` acepta la primera fecha con hora del texto ("01 Octubre de
    2026 – 11:00 horas"); úsalo solo en páginas donde esa es la fecha de los precios.
    """
    plain = _strip_accents(text)
    m = _UPDATED_RE.search(plain) or (None if require_label else _ANY_DATE_RE.search(plain))
    if not m:
        return None
    day, month_name, year, hour, minute = m.groups()
    month = _MONTHS.get(month_name.lower())
    if not month:
        return None
    try:
        local = datetime(int(year), month, int(day), int(hour), int(minute), tzinfo=ZoneInfo(tz))
    except ValueError:
        return None
    return local.astimezone(timezone.utc)


def says_no_commission(text: str) -> bool:
    return bool(_NO_COMMISSION_RE.search(_strip_accents(text)))


class HtmlTableScraper(BaseScraper):
    """Lee las tablas Moneda | Compra | Venta de ``source_url``."""

    #: slug de la casa en data/exchange_houses.json
    house_slug: str = ""
    #: separador decimal si la casa lo usa de forma ambigua (None = deducir)
    decimal_separator: str | None = None
    #: leer "Última actualización ..." como hora publicada de la cotización
    reads_update_time: bool = False
    #: aceptar una fecha con hora sin la palabra "actualización" (la página solo tiene esa fecha)
    update_time_requires_label: bool = True
    #: si la página dice "Sin comisiones"/"0% comisiones", registrar comisión 0 (dato publicado)
    reads_no_commission: bool = False
    #: nota fija que acompaña cada cotización (p. ej. "valores referenciales")
    notes: str | None = None

    def scrape(self) -> list[NormalizedQuote]:
        return self.parse(self.http_get(self.source_url).text)

    def parse(self, html: str, url: str | None = None, branch: str | None = None) -> list[NormalizedQuote]:
        url = url or self.source_url
        rates = _dedupe(parse_html_rate_table(html, self.decimal_separator))
        if not rates:
            raise StructureChangedError(f"no se encontró la tabla de cotizaciones en {url}")
        text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
        published = (parse_spanish_update_time(text, require_label=self.update_time_requires_label)
                     if self.reads_update_time else None)
        if self.reads_update_time and published is None:
            self.log.warning("%s: no se encontró la hora de actualización publicada", self.slug)
        commission = 0.0 if self.reads_no_commission and says_no_commission(text) else None
        notes = [self.notes] if self.notes else []
        if commission == 0.0:
            notes.append("la página indica que no cobra comisión")
        return [
            NormalizedQuote(
                exchange_house=self.house_slug or self.slug,
                currency=r.currency,
                buy_rate=r.buy_rate,
                sell_rate=r.sell_rate,
                source_url=url,
                timestamp_source=published,
                branch=branch,
                commission_percent=commission,
                commission_fixed=commission,
                notes="; ".join(notes) or None,
            )
            for r in rates
        ]


def _dedupe(rates: list[RawRate]) -> list[RawRate]:
    """Si una divisa aparece dos veces, se usa la primera (la tabla principal)."""
    seen: dict[str, RawRate] = {}
    for r in rates:
        if r.currency != "CLP":
            seen.setdefault(r.currency, r)
    return list(seen.values())
