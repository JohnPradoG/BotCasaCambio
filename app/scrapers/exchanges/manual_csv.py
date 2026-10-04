"""Cotizaciones ingresadas a mano (SPEC §44: registro manual).

Útil para cargar precios confirmados por teléfono/WhatsApp o tomados de una
pizarra física. El archivo es ``data/manual_quotes.csv`` (``MANUAL_QUOTES_FILE``).

Columnas (solo las 4 primeras son obligatorias; vacío = desconocido):

    exchange_house, currency, buy_rate, sell_rate, source_url, timestamp_source,
    availability, min_amount, max_amount, commission_fixed, commission_percent,
    branch, notes

``buy_rate`` / ``sell_rate`` siguen la convención estándar: lo que la casa paga /
cobra por 1 unidad de divisa, en CLP. ``source_url`` puede ser un enlace o una
referencia como ``tel:+56...`` o ``manual:pizarra`` para mantener la trazabilidad.
"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from app.models.currency import normalize_currency_code
from app.models.quote import NormalizedQuote
from app.scrapers.base import BaseScraper
from app.scrapers.normalization import parse_rate
from app.scrapers.registry import register

COLUMNS = [
    "exchange_house", "currency", "buy_rate", "sell_rate", "source_url", "timestamp_source",
    "availability", "min_amount", "max_amount", "commission_fixed", "commission_percent",
    "branch", "notes",
]


def _opt(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _parse_bool(value: str | None) -> bool | None:
    value = (_opt(value) or "").lower()
    if value in {"1", "true", "si", "sí", "yes", "disponible"}:
        return True
    if value in {"0", "false", "no", "agotado", "sin stock"}:
        return False
    return None


@register
class ManualCsvScraper(BaseScraper):
    slug = "manual_csv"
    verified = True
    empty_is_ok = True  # un CSV vacío no es un cambio de estructura

    def __init__(self, *args, path: str | Path | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.path = Path(path or self.settings.manual_quotes_file)
        self.source_url = f"file://{self.path}"

    def scrape(self) -> list[NormalizedQuote]:
        if not self.path.exists():
            self.log.info("No existe %s; no hay cotizaciones manuales", self.path)
            return []
        quotes: list[NormalizedQuote] = []
        with self.path.open(newline="", encoding="utf-8") as fh:
            rows = [r for r in csv.DictReader(fh) if any((v or "").strip() for v in r.values())]
        for line, row in enumerate(rows, start=2):
            currency = normalize_currency_code(row.get("currency"))
            if not currency:
                self.log.warning("Línea %d: divisa no reconocida %r", line, row.get("currency"))
                continue
            ts = _opt(row.get("timestamp_source"))
            quotes.append(
                NormalizedQuote(
                    exchange_house=(_opt(row.get("exchange_house")) or ""),
                    currency=currency,
                    buy_rate=parse_rate(_opt(row.get("buy_rate"))),
                    sell_rate=parse_rate(_opt(row.get("sell_rate"))),
                    source_url=_opt(row.get("source_url")) or f"manual:{self.path.name}#L{line}",
                    timestamp_source=datetime.fromisoformat(ts) if ts else None,
                    availability=_parse_bool(row.get("availability")),
                    min_amount=parse_rate(_opt(row.get("min_amount"))),
                    max_amount=parse_rate(_opt(row.get("max_amount"))),
                    commission_fixed=parse_rate(_opt(row.get("commission_fixed"))),
                    commission_percent=parse_rate(_opt(row.get("commission_percent")), decimal_separator=None),
                    branch=_opt(row.get("branch")),
                    notes=_opt(row.get("notes")),
                )
            )
        return quotes
