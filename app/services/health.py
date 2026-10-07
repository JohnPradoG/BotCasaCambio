"""Estado de las casas que publican precios en la web (``/estado`` y aviso diario).

Se vigilan las casas que el bot leyó de su web (no a mano) en los últimos días. Una casa
tiene problema si no se lee hace más de ``stale_hours`` horas, o si la web muestra
precios publicados hace más de ``MAX_QUOTE_USABLE_HOURS`` (se usan con aviso de confirmar).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import ExchangeHouseRow, QuoteRow, ScraperRunRow
from app.scrapers.base import ScraperStatus

MANUAL_SCRAPER = "manual_csv"
OK, NOT_READ, OLD_PRICES = "ok", "sin_lectura", "precio_viejo"
_WORKING = (ScraperStatus.OK.value, ScraperStatus.PARTIAL.value)


def _aware(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt


@dataclass
class HouseHealth:
    house: str
    state: str
    last_read: datetime
    published: datetime | None = None  # hora más reciente que muestra la web, si la muestra


def house_health(session: Session, now: datetime, stale_hours: float, usable_hours: float,
                 window_days: int = 7) -> list[HouseHealth]:
    rows = session.execute(
        select(ExchangeHouseRow.name, QuoteRow.timestamp_collected, QuoteRow.timestamp_source)
        .join(QuoteRow, QuoteRow.exchange_house_id == ExchangeHouseRow.id)
        .join(ScraperRunRow, QuoteRow.scraper_run_id == ScraperRunRow.id)
        .where(ScraperRunRow.scraper != MANUAL_SCRAPER,
               QuoteRow.timestamp_collected >= now - timedelta(days=window_days))
    ).all()
    last: dict[str, datetime] = {}
    published: dict[str, list[datetime | None]] = {}
    for name, collected, source in rows:
        collected, source = _aware(collected), _aware(source)
        if name not in last or collected > last[name]:
            last[name] = collected
            published[name] = [source]
        elif collected == last[name]:
            published[name].append(source)
    result = []
    for name, read in last.items():
        shown = [p for p in published[name] if p is not None]
        newest = max(shown) if len(shown) == len(published[name]) and shown else None  # todas fechadas
        if read < now - timedelta(hours=stale_hours):
            state = NOT_READ
        elif newest is not None and newest < now - timedelta(hours=usable_hours):
            state = OLD_PRICES
        else:
            state = OK
        result.append(HouseHealth(name, state, read, newest))
    result.sort(key=lambda h: (h.state == OK, h.house.lower()))
    return result


def failing_readers(session: Session, now: datetime, hours: float = 1) -> dict[str, str]:
    """Último error de cada lector que falló en su última ejecución reciente (sin el de precios a mano)."""
    runs = session.scalars(
        select(ScraperRunRow).where(ScraperRunRow.started_at >= now - timedelta(hours=hours),
                                    ScraperRunRow.scraper != MANUAL_SCRAPER)
        .order_by(ScraperRunRow.started_at.desc(), ScraperRunRow.id.desc())
    ).all()
    latest: dict[str, ScraperRunRow] = {}
    for run in runs:
        latest.setdefault(run.scraper, run)
    return {s: (r.error or r.status)[:120] for s, r in sorted(latest.items()) if r.status not in _WORKING}


def _when(dt: datetime, zone: ZoneInfo, now: datetime) -> str:
    local = dt.astimezone(zone)
    return local.strftime("%H:%M") if local.date() == now.astimezone(zone).date() else local.strftime("%d/%m %H:%M")


def health_line(h: HouseHealth, zone: ZoneInfo, now: datetime) -> str:
    if h.state == NOT_READ:
        return f"❌ {h.house}: no se lee desde {_when(h.last_read, zone, now)}"
    if h.state == OLD_PRICES:
        return (f"⚠️ {h.house}: la web muestra precios del {h.published.astimezone(zone).strftime('%d/%m')}; "
                "se usan, pero hay que confirmarlos")
    return f"✅ {h.house}: leída {_when(h.last_read, zone, now)}"


def health_text(houses: list[HouseHealth], failing: dict[str, str], now: datetime,
                tz: str = "America/Santiago", only_problems: bool = False) -> str | None:
    zone = ZoneInfo(tz)
    shown = [h for h in houses if h.state != OK] if only_problems else houses
    if only_problems and not shown:
        return None
    if not houses:
        return "🩺 Todavía no hay casas leídas desde su web."
    ok = sum(h.state == OK for h in houses)
    title = "🩺 Casas con problemas para leer precios" if only_problems else "🩺 Estado de las casas con precio en la web"
    lines = [title, f"{ok} de {len(houses)} funcionando."]
    lines += [health_line(h, zone, now) for h in shown]
    if failing and not only_problems:
        lines.append("Lectores con error en la última hora:")
        lines += [f"• {s}: {e}" for s, e in failing.items()]
    if only_problems:
        lines.append("Puede que la casa cambió su web o la tiene caída. Detalle: /estado")
    return "\n".join(lines)
