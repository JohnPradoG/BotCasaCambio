"""Registro manual de casas de cambio y sus sucursales (SPEC §44)."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import timedelta
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database.models import BranchRow, ExchangeHouseRow, QuoteRow
from app.models.exchange_house import ExchangeHouse
from app.models.quote import utcnow

logger = logging.getLogger(__name__)


def load_houses_file(path: str | Path) -> list[ExchangeHouse]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [ExchangeHouse.from_dict(item) for item in data.get("exchange_houses", [])]


def merge_houses(base: list[ExchangeHouse], extra: list[ExchangeHouse]) -> list[ExchangeHouse]:
    """Une el registro con casas de otra fuente (Google Maps).

    Si la casa ya existe, solo se completan web/teléfono faltantes y se agregan sucursales
    nuevas; nunca se pisa un dato del registro.
    """
    by_slug = {h.slug: h for h in base}
    merged = list(base)
    for house in extra:
        current = by_slug.get(house.slug)
        if current is None:
            merged.append(house)
            by_slug[house.slug] = house
            continue
        current.website = current.website or house.website
        current.phone = current.phone or house.phone
        names = {b.name for b in current.branches}
        current.branches += [b for b in house.branches if b.name not in names]
    return merged


def load_all_houses(settings) -> list[ExchangeHouse]:
    """Registro (``HOUSES_FILE``) + casas encontradas en Google Maps (``maps_houses.json``)."""
    base = load_houses_file(settings.houses_file) if Path(settings.houses_file).exists() else []
    maps = Path(settings.maps_houses_path)
    if maps.exists():
        try:
            base = merge_houses(base, load_houses_file(maps))
        except (ValueError, TypeError) as exc:
            logger.warning("No se pudo leer %s: %s", maps, exc)
    return base


def upsert_house(session: Session, house: ExchangeHouse) -> ExchangeHouseRow:
    row = session.scalar(select(ExchangeHouseRow).where(ExchangeHouseRow.slug == house.slug))
    fields = {k: v for k, v in asdict(house).items() if k != "branches"}
    if row is None:
        row = ExchangeHouseRow(**fields)
        session.add(row)
    else:
        for key, value in fields.items():
            setattr(row, key, value)
    existing = {b.name: b for b in row.branches}
    seen: set[str] = set()
    for branch in house.branches:
        values = asdict(branch)
        values["name"] = unique_name(branch.name, seen)  # dos sucursales con el mismo nombre no chocan
        seen.add(values["name"])
        if values["name"] in existing:
            for key, value in values.items():
                setattr(existing[values["name"]], key, value)
        else:
            existing[values["name"]] = BranchRow(**values)
            row.branches.append(existing[values["name"]])
    session.flush()
    return row


def unique_name(name: str, taken: set[str]) -> str:
    """"Centro" → "Centro (2)" si ya hay otra sucursal "Centro" en la misma casa."""
    if name not in taken:
        return name
    n = 2
    while f"{name} ({n})" in taken:
        n += 1
    return f"{name} ({n})"


def sync_houses(session: Session, path: str | Path) -> int:
    houses = load_houses_file(path)
    for house in houses:
        upsert_house(session, house)
    logger.info("%d casas registradas desde %s", len(houses), path)
    return len(houses)


def sync_all_houses(session: Session, settings) -> int:
    """Registro + casas del mapa. Una casa con datos que no se pueden guardar se salta (queda en el log)."""
    houses = load_all_houses(settings)
    for house in houses:
        try:
            with session.begin_nested():
                upsert_house(session, house)
        except SQLAlchemyError as exc:
            logger.error("No se pudo registrar la casa %s: %s", house.slug, exc)
    return len(houses)


def ensure_house(session: Session, slug: str) -> ExchangeHouseRow:
    """Devuelve la casa; si no está registrada, crea una mínima con solo el slug (sin inventar datos)."""
    row = session.scalar(select(ExchangeHouseRow).where(ExchangeHouseRow.slug == slug))
    if row is None:
        logger.warning("Casa %r no registrada en exchange_houses.json; se crea sin datos de contacto", slug)
        row = ExchangeHouseRow(slug=slug, name=slug, notes="creada automáticamente desde una cotización")
        session.add(row)
        session.flush()
    return row


@dataclass
class HouseStats:
    discovered: int
    with_active_quotes: int
    unavailable: int


def house_stats(session: Session, max_age_minutes: int) -> HouseStats:
    """Resumen pedido en SPEC §44."""
    discovered = session.scalar(select(func.count()).select_from(ExchangeHouseRow)) or 0
    since = utcnow() - timedelta(minutes=max_age_minutes)
    active = session.scalar(
        select(func.count(func.distinct(QuoteRow.exchange_house_id))).where(QuoteRow.timestamp_collected >= since)
    ) or 0
    return HouseStats(discovered=discovered, with_active_quotes=active, unavailable=discovered - active)


def house_directory(session: Session) -> dict[str, ExchangeHouse]:
    """Casas y sucursales registradas, como modelos de dominio, para el motor."""
    from app.models.exchange_house import Branch

    directory: dict[str, ExchangeHouse] = {}
    for row in session.scalars(select(ExchangeHouseRow)):
        directory[row.slug] = ExchangeHouse(
            slug=row.slug, name=row.name, website=row.website, quotes_url=row.quotes_url, phone=row.phone,
            whatsapp=row.whatsapp, source_url=row.source_url, scraper=row.scraper, notes=row.notes,
            branches=[
                Branch(name=b.name, address=b.address, comuna=b.comuna, phone=b.phone, whatsapp=b.whatsapp,
                       opening_hours=b.opening_hours, schedule=b.schedule, latitude=b.latitude,
                       longitude=b.longitude, source_url=b.source_url, verified=b.verified, notes=b.notes)
                for b in row.branches
            ],
        )
    return directory
