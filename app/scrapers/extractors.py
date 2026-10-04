"""Extractores reutilizables para JSON embebido/API y para tablas HTML.

Cada scraper específico decide cuál usar; estos helpers solo encuentran pares
(divisa, compra, venta) y delegan el significado de las etiquetas a
:func:`classify_rate_label`, de modo que la regla compra/venta vive en un único lugar.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterator

from bs4 import BeautifulSoup

from app.models.currency import _ALIASES, KNOWN_CODES, _strip_accents, normalize_currency_code
from app.scrapers.normalization import RateParseError, classify_rate_label, parse_rate

_CURRENCY_KEYS = {"currency", "moneda", "divisa", "code", "codigo", "iso", "symbol", "simbolo", "name", "nombre"}


@dataclass
class RawRate:
    currency: str
    buy_rate: float | None
    sell_rate: float | None
    raw: Any = None


def _walk(obj: Any) -> Iterator[dict]:
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from _walk(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from _walk(item)


def find_rate_records(data: Any, decimal_separator: str | None = None) -> list[RawRate]:
    """Busca, en cualquier JSON, objetos con una divisa y campos de compra/venta."""
    found: list[RawRate] = []
    for node in _walk(data):
        currency = None
        for key, value in node.items():
            if str(key).lower() in _CURRENCY_KEYS and isinstance(value, str):
                currency = normalize_currency_code(value)
                if currency:
                    break
        if not currency:
            continue
        sides: dict[str, float | None] = {}
        for key, value in node.items():
            side = classify_rate_label(str(key).replace("_", " "))
            if side is None or side in sides or isinstance(value, (dict, list, bool)):
                continue
            try:
                sides[side] = parse_rate(value, decimal_separator)
            except RateParseError:
                continue
        if sides.get("buy") is not None or sides.get("sell") is not None:
            found.append(RawRate(currency, sides.get("buy"), sides.get("sell"), raw=node))
    return found


def parse_html_rate_table(html: str, decimal_separator: str | None = None) -> list[RawRate]:
    """Lee tablas con encabezados del tipo Moneda | Compra | Venta (en cualquier orden)."""
    soup = BeautifulSoup(html, "html.parser")
    results: list[RawRate] = []
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue
        headers = [c.get_text(" ", strip=True) for c in rows[0].find_all(["th", "td"])]
        side_cols = {i: classify_rate_label(h) for i, h in enumerate(headers)}
        if "buy" not in side_cols.values() and "sell" not in side_cols.values():
            continue
        for row in rows[1:]:
            cells = [c.get_text(" ", strip=True) for c in row.find_all(["th", "td"])]
            if not cells:
                continue
            currency = next((normalize_currency_code(c) for c in cells if normalize_currency_code(c)), None)
            if not currency:
                continue
            values: dict[str, float | None] = {}
            for i, side in side_cols.items():
                if side and i < len(cells) and side not in values:
                    try:
                        values[side] = parse_rate(cells[i], decimal_separator)
                    except RateParseError:
                        values[side] = None
            if values.get("buy") is not None or values.get("sell") is not None:
                results.append(RawRate(currency, values.get("buy"), values.get("sell"), raw=cells))
    return results


_NUM = r"\$?\s*([\d][\d.,]*)"


def find_inline_rates(text: str, decimal_separator: str | None = None, window: int = 120) -> list[RawRate]:
    """Busca patrones "<divisa> ... Compra 940 · Venta 970" en texto plano (p. ej. página renderizada).

    La divisa se toma de la mención más cercana *antes* del par compra/venta,
    dentro de ``window`` caracteres. Si no hay una divisa clara, el par se descarta.
    """
    label = r"(compra|compramos|venta|vendemos)"
    pair_re = re.compile(rf"{label}\s*:?\s*{_NUM}\s*[·|/\-–—,;]?\s*{label}\s*:?\s*{_NUM}", re.IGNORECASE)
    names = sorted(_ALIASES, key=len, reverse=True)
    currency_re = re.compile(
        r"\b(" + "|".join(sorted(KNOWN_CODES)) + r")\b|\b(" + "|".join(re.escape(n) for n in names) + r")\b",
        re.IGNORECASE,
    )
    plain = _strip_accents(text)
    results: list[RawRate] = []
    for m in pair_re.finditer(plain):
        before = plain[max(0, m.start() - window): m.start()]
        mentions = list(currency_re.finditer(before))
        if not mentions:
            continue
        currency = normalize_currency_code(mentions[-1].group(0))
        if not currency or currency == "CLP":
            # "Precio del dólar en pesos chilenos": buscamos la última mención que no sea CLP.
            others = [normalize_currency_code(x.group(0)) for x in mentions]
            others = [c for c in others if c and c != "CLP"]
            if not others:
                continue
            currency = others[-1]
        values: dict[str, float | None] = {}
        for lbl, num in ((m.group(1), m.group(2)), (m.group(3), m.group(4))):
            side = classify_rate_label(lbl)
            if side and side not in values:
                try:
                    values[side] = parse_rate(num.rstrip(".,"), decimal_separator)
                except RateParseError:
                    values[side] = None
        if values.get("buy") is not None or values.get("sell") is not None:
            results.append(RawRate(currency, values.get("buy"), values.get("sell"), raw=m.group(0)))
    return results


def extract_rates(html: str, decimal_separator: str | None = None) -> list[RawRate]:
    """Tablas Moneda | Compra | Venta y, si no hay, texto "Compra X · Venta Y". Una fila por divisa."""
    rates = parse_html_rate_table(html, decimal_separator)
    if not rates:
        rates = find_inline_rates(BeautifulSoup(html, "html.parser").get_text(" ", strip=True), decimal_separator)
    seen: dict[str, RawRate] = {}
    for r in rates:
        if r.currency != "CLP":
            seen.setdefault(r.currency, r)
    return list(seen.values())
