"""Carga rápida de precios a mano (pizarra, teléfono, WhatsApp) en ``MANUAL_QUOTES_FILE``.

Muchas casas de cambio (sobre todo en el centro) no publican precios en internet.
Esta es la forma de agregarlos sin editar el CSV: desde la línea de comandos
(``add-quote``) o desde Telegram (``/precio``).

Una entrada nueva reemplaza la anterior de la misma casa, divisa y sucursal, y
queda con la hora en que se ingresó (``timestamp_source``), así que su antigüedad
cuenta para la confianza igual que la de un scraper.
"""

from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.models.currency import normalize_currency_code
from app.models.quote import utcnow
from app.scrapers.exchanges.manual_csv import COLUMNS
from app.scrapers.normalization import RateParseError, parse_rate


class ManualEntryError(ValueError):
    pass


@dataclass
class ManualPrice:
    house: str
    currency: str
    buy_rate: float | None
    sell_rate: float | None
    branch: str | None = None


USAGE = (
    "Formato: /precio <casa> <divisa> <compra> <venta>\n"
    "Ejemplo: /precio gamaex USD 970 990\n"
    "compra = lo que la casa te paga por 1 unidad; venta = lo que te cobra. Usa - si no lo sabes."
)


def slugify(name: str) -> str:
    text = "".join(c for c in unicodedata.normalize("NFD", name) if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def resolve_house(token: str, known: dict[str, str]) -> str:
    """Busca la casa por slug o nombre (``known`` = {slug: nombre}); si no existe, usa el slug del texto."""
    wanted = slugify(token)
    for slug, name in known.items():
        if wanted in (slug, slugify(name)):
            return slug
    return wanted


def _rate(raw: str) -> float | None:
    if raw.strip() in {"-", "?", "x"}:
        return None
    try:
        value = parse_rate(raw)
    except RateParseError as exc:
        raise ManualEntryError(f"precio no válido: {raw!r}") from exc
    if value is not None and value <= 0:
        raise ManualEntryError(f"precio no válido: {raw!r}")
    return value


def parse_price_command(text: str, known: dict[str, str] | None = None) -> ManualPrice:
    """Lee ``/precio <casa> <divisa> <compra> <venta>``. El nombre de la casa puede tener espacios."""
    parts = text.strip().split()
    if parts and parts[0].startswith("/"):
        parts = parts[1:]
    if len(parts) < 4:
        raise ManualEntryError(USAGE)
    *house_words, currency_raw, buy_raw, sell_raw = parts
    currency = normalize_currency_code(currency_raw)
    if not currency or currency == "CLP":
        raise ManualEntryError(f"divisa no reconocida: {currency_raw!r}\n{USAGE}")
    buy, sell = _rate(buy_raw), _rate(sell_raw)
    if buy is None and sell is None:
        raise ManualEntryError("falta el precio de compra o de venta")
    house = resolve_house(" ".join(house_words), known or {})
    if not house:
        raise ManualEntryError(USAGE)
    return ManualPrice(house, currency, buy, sell)


def _fmt(value: float | None) -> str:
    return "" if value is None else f"{value:g}"


def save_manual_price(path: str | Path, price: ManualPrice, source: str, when: datetime | None = None,
                      notes: str | None = None) -> None:
    """Agrega o reemplaza la fila (casa, divisa, sucursal) en el CSV manual."""
    path = Path(path)
    when = when or utcnow()
    rows: list[dict] = []
    if path.exists():
        with path.open(newline="", encoding="utf-8") as fh:
            rows = [r for r in csv.DictReader(fh) if any((v or "").strip() for v in r.values())]
    key = (price.house, price.currency, price.branch or "")
    rows = [r for r in rows if (r.get("exchange_house", "").strip(), normalize_currency_code(r.get("currency")) or "",
                                (r.get("branch") or "").strip()) != key]
    rows.append({
        "exchange_house": price.house, "currency": price.currency, "buy_rate": _fmt(price.buy_rate),
        "sell_rate": _fmt(price.sell_rate), "source_url": source, "timestamp_source": when.isoformat(),
        "branch": price.branch or "", "notes": notes or "",
    })
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({c: row.get(c) or "" for c in COLUMNS})
    tmp.replace(path)
