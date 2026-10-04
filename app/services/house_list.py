"""Planilla de casas con y sin precio, con sus datos de contacto, para llamar a consultar.

Una fila por sucursal (o una por casa si no tiene sucursales). "Con precio" = el bot
guardó al menos una cotización de esa casa en las últimas ``MAX_QUOTE_USABLE_HOURS``.
Solo se copian datos del registro y del mapa; lo desconocido queda vacío.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database.models import ExchangeHouseRow, QuoteRow
from app.models.exchange_house import ExchangeHouse
from app.models.quote import utcnow

COLUMNS = ["estado", "casa", "sucursal", "direccion", "comuna", "telefono", "whatsapp", "horario", "web",
           "ultimo_precio", "divisas", "origen", "fuente"]
WITH_PRICE, WITHOUT_PRICE = "Con precio", "Sin precio"


@dataclass
class PriceStatus:
    last_collected: datetime
    currencies: int


def price_status(session: Session, max_age_hours: float) -> dict[str, PriceStatus]:
    since = utcnow() - timedelta(hours=max_age_hours)
    rows = session.execute(
        select(ExchangeHouseRow.slug, func.max(QuoteRow.timestamp_collected), func.count(func.distinct(QuoteRow.currency)))
        .join(QuoteRow, QuoteRow.exchange_house_id == ExchangeHouseRow.id)
        .where(QuoteRow.timestamp_collected >= since)
        .group_by(ExchangeHouseRow.slug)
    ).all()
    return {slug: PriceStatus(last, n) for slug, last, n in rows}


def _origin(house: ExchangeHouse) -> str:
    notes = house.notes or ""
    for source in ("OpenStreetMap", "Google Maps"):
        if f"Encontrada en {source}" in notes:
            return source
    return "Registro"


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)  # SQLite devuelve fechas sin zona (UTC)


def build_rows(houses: list[ExchangeHouse], status: dict[str, PriceStatus], tz: str = "America/Santiago") -> list[dict]:
    zone = ZoneInfo(tz)
    rows = []
    for h in houses:
        st = status.get(h.slug)
        base = {
            "estado": WITH_PRICE if st else WITHOUT_PRICE, "casa": h.name, "web": h.website or "",
            "ultimo_precio": _aware(st.last_collected).astimezone(zone).strftime("%Y-%m-%d %H:%M") if st else "",
            "divisas": st.currencies if st else "", "origen": _origin(h),
        }
        for b in h.branches or [None]:
            rows.append({**base,
                         "sucursal": b.name if b else "", "direccion": (b.address if b else None) or "",
                         "comuna": (b.comuna if b else None) or "",
                         "telefono": (b.phone if b else None) or h.phone or "",
                         "whatsapp": (b.whatsapp if b else None) or h.whatsapp or "",
                         "horario": (b.opening_hours if b else None) or "",
                         "fuente": (b.source_url if b else None) or h.source_url or ""})
    # Primero las que hay que llamar (sin precio), y dentro de ellas las que tienen teléfono.
    rows.sort(key=lambda r: (r["estado"] == WITH_PRICE, not r["telefono"], r["casa"].lower(), r["sucursal"].lower()))
    return rows


def write_csv(rows: list[dict], path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:  # BOM: Excel muestra bien las tildes
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return path


def summary(rows: list[dict]) -> str:
    houses = {(r["estado"], r["casa"]) for r in rows}
    with_price = sorted(c for e, c in houses if e == WITH_PRICE)
    without = [c for e, c in houses if e == WITHOUT_PRICE]
    callable_ = {r["casa"] for r in rows if r["estado"] == WITHOUT_PRICE and (r["telefono"] or r["whatsapp"])}
    return (f"📋 Casas: {len(with_price)} con precio, {len(without)} sin precio "
            f"({len(callable_)} de ellas con teléfono).\n"
            f"Con precio: {', '.join(with_price) or 'ninguna'}.")
