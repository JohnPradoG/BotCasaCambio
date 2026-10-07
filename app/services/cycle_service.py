"""Un ciclo completo del bot (SPEC §52): cotizaciones → rutas → guardado → alerta → seguimiento."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config.settings import Settings
from app.database.models import OpportunityRow
from app.models.quote import utcnow
from app.notifications.messages import format_alert, format_drop_alert
from app.notifications.telegram import ConsoleNotifier, TelegramNotifier
from app.scrapers.registry import get_scrapers
from app.services.arbitrage_engine import Route, SearchStats, find_best_routes, reprice_route
from app.services.house_service import house_directory, sync_all_houses
from app.services.market_reference import find_gaps, gaps_text, get_reference
from app.services.usdt_spread import check_usdt_spreads, fetch_all
from app.services.opportunity_service import quotes_for_engine, save_routes
from app.services.quote_service import collect_quotes
from app.services.verification_service import expire_old

logger = logging.getLogger(__name__)


@dataclass
class CycleResult:
    routes: list[Route] = field(default_factory=list)
    alerted: list[Route] = field(default_factory=list)
    drop_alerts: list[str] = field(default_factory=list)  # firmas de rutas cuya baja se avisó
    market_alerts: list[str] = field(default_factory=list)  # "casa:lado" avisados fuera de mercado
    usdt_alerts: list[str] = field(default_factory=list)  # "A>B" diferencias USDT avisadas
    quotes_used: int = 0
    expired: int = 0
    stats: SearchStats = field(default_factory=SearchStats)


def make_notifier(settings: Settings):
    if settings.telegram_enabled:
        return TelegramNotifier(settings.telegram_bot_token, settings.telegram_chat_id)
    return ConsoleNotifier()


def should_alert(session: Session, route: Route, settings: Settings) -> bool:
    """Alerta si la ruta es nueva o mejoró lo suficiente desde la última alerta (SPEC §23, §52.10-11)."""
    if route.net_profit_clp < settings.min_net_profit_clp:
        return False
    since = utcnow() - timedelta(minutes=settings.alert_cooldown_minutes)
    last = session.scalar(
        select(OpportunityRow)
        .where(OpportunityRow.signature == route.signature, OpportunityRow.alerted.is_(True),
               OpportunityRow.alerted_at >= since)
        .order_by(OpportunityRow.alerted_at.desc())
    )
    if last is None:
        return True
    return route.net_profit_clp >= last.net_profit_clp * (1 + settings.alert_min_improvement_percent / 100)


_WATCHED_STATUSES = ("DETECTED", "PENDING_VERIFICATION", "VERIFIED")


def check_drops(session: Session, quotes, settings: Settings, directory: dict, notifier, now=None) -> list[str]:
    """Avisa si una ruta ya alertada perdió ``ALERT_DROP_PERCENT`` % o más de su ganancia neta.

    La ruta se recalcula con las mismas operaciones y las cotizaciones actuales, aunque ya no
    esté en el Top. Cada aviso pasa a ser la nueva referencia, así que una baja no se repite
    en cada ciclo; una ruta que desaparece se avisa una sola vez.
    """
    if settings.alert_drop_percent <= 0:
        return []
    now = now or utcnow()
    since = now - timedelta(minutes=settings.opportunity_ttl_minutes)
    rows = session.scalars(
        select(OpportunityRow)
        .where(OpportunityRow.alerted.is_(True), OpportunityRow.alerted_at >= since,
               OpportunityRow.status.in_(_WATCHED_STATUSES), OpportunityRow.signature.is_not(None))
        .order_by(OpportunityRow.alerted_at.desc())
    ).all()
    latest: dict[str, OpportunityRow] = {}
    for row in rows:
        latest.setdefault(row.signature, row)

    tz = ZoneInfo(settings.timezone)
    sent: list[str] = []
    for signature, row in latest.items():
        details = dict(row.details or {})
        if details.get("drop_gone_notified"):
            continue
        reference = details.get("last_notified_net_profit", row.net_profit_clp)
        if reference <= 0:
            continue
        current = reprice_route(signature, quotes, row.initial_clp, settings, directory, now=now)
        current_profit = current.net_profit_clp if current is not None else None
        if current_profit is not None and current_profit > reference * (1 - settings.alert_drop_percent / 100):
            continue
        drop = 100.0 if current_profit is None else (reference - current_profit) / reference * 100
        notified_at = details.get("last_notified_at") or row.alerted_at.isoformat()
        when = datetime.fromisoformat(notified_at) if isinstance(notified_at, str) else notified_at
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        route_text = " → ".join(details.get("currencies") or []) or signature
        houses = " → ".join(directory[h].name if h in directory else h for h in details.get("houses") or []) or "-"
        text = format_drop_alert(route_text, houses, reference, current, when.astimezone(tz).strftime("%H:%M"), drop)
        if not notifier.send(text):
            continue
        if current_profit is None or current_profit <= 0:
            details["drop_gone_notified"] = True
        details["last_notified_net_profit"] = current_profit if current_profit is not None else 0.0
        details["last_notified_at"] = now.isoformat()
        row.details = details
        sent.append(signature)
        logger.info("Aviso de baja enviado: %s (%.0f%%)", signature, drop)
    return sent


_market_alerted: dict[str, datetime] = {}  # "casa:lado" -> último aviso (en memoria)
_usdt_alerted: dict[str, datetime] = {}  # "A>B" -> último aviso (en memoria)


def _usdt_spreads(settings: Settings, notifier) -> list[str]:
    if not settings.usdt_venues.strip():
        return []
    try:
        return check_usdt_spreads(fetch_all(settings), settings, notifier, utcnow(), _usdt_alerted)
    except Exception:  # opcional: nunca debe cortar el ciclo
        logger.exception("No se pudo revisar la diferencia de USDT")
        return []


def _market_ref(settings: Settings):
    if not settings.market_reference.strip():
        return None
    try:
        return get_reference(settings)
    except Exception:  # la referencia es opcional: nunca debe cortar el ciclo
        logger.exception("No se pudo leer el dólar de mercado")
        return None


def check_market_gaps(quotes, ref, settings: Settings, directory: dict, notifier, now=None,
                      state: dict[str, datetime] | None = None) -> list[str]:
    """Avisa de casas cuyo dólar está fuera de mercado, una vez cada ``MARKET_ALERT_COOLDOWN_HOURS``."""
    if ref is None:
        return []
    now = now or utcnow()
    state = _market_alerted if state is None else state
    names = {slug: h.name for slug, h in directory.items()}
    gaps = find_gaps(quotes, ref, settings.market_gap_percent, names)
    cooldown = timedelta(hours=settings.market_alert_cooldown_hours)
    fresh = [g for g in gaps if f"{g.house}:{g.side}" not in state or now - state[f"{g.house}:{g.side}"] >= cooldown]
    if not fresh or not notifier.send(gaps_text(fresh) + "\n" + f"Fuente: {ref.url}"):
        return []
    keys = [f"{g.house}:{g.side}" for g in fresh]
    for key in keys:
        state[key] = now
    logger.info("Aviso fuera de mercado: %s", ", ".join(keys))
    return keys


def run_cycle(session: Session, settings: Settings, scrape: bool = True, notifier=None,
              capital: float | None = None, top_n: int | None = None, max_steps: int | None = None,
              save: bool = True, alert: bool = True) -> CycleResult:
    result = CycleResult()
    sync_all_houses(session, settings)
    if scrape:
        collect_quotes(session, get_scrapers(settings.enabled_scraper_list, settings=settings), settings)

    quotes = quotes_for_engine(session, settings.max_quote_usable_hours * 60)
    result.quotes_used = len(quotes)
    directory = house_directory(session)
    result.routes = find_best_routes(
        quotes, initial_amount=capital if capital is not None else settings.initial_capital_clp,
        max_steps=max_steps, top_n=top_n, settings=settings, stats=result.stats, directory=directory,
    )
    if save:
        rows = save_routes(session, result.routes)
        if alert:
            to_alert = [r for r in result.routes if should_alert(session, r, settings)]
            if to_alert:
                notifier = notifier or make_notifier(settings)
                worth = [r for r in result.routes if r.net_profit_clp >= settings.min_net_profit_clp]
                text = format_alert(worth, directory, result.routes[0].initial_clp, market=_market_ref(settings))
                if notifier.send(text):
                    now = utcnow()
                    alerted_sigs = {r.signature for r in worth}
                    for row in rows:
                        if row.signature in alerted_sigs:
                            row.alerted, row.alerted_at = True, now
                    result.alerted = worth
            notifier = notifier or make_notifier(settings)
            result.drop_alerts = check_drops(session, quotes, settings, directory, notifier)
            result.market_alerts = check_market_gaps(quotes, _market_ref(settings), settings, directory, notifier)
            result.usdt_alerts = _usdt_spreads(settings, notifier)
        result.expired = expire_old(session, settings.opportunity_ttl_minutes)
    session.flush()
    return result
