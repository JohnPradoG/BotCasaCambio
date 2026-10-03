"""Un ciclo completo del bot (SPEC §52): cotizaciones → rutas → guardado → alerta → seguimiento."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config.settings import Settings
from app.database.models import OpportunityRow
from app.models.quote import utcnow
from app.notifications.messages import format_alert
from app.notifications.telegram import ConsoleNotifier, TelegramNotifier
from app.scrapers.registry import get_scrapers
from app.services.arbitrage_engine import Route, SearchStats, find_best_routes
from app.services.house_service import house_directory, sync_houses
from app.services.opportunity_service import quotes_for_engine, save_routes
from app.services.quote_service import collect_quotes
from app.services.verification_service import expire_old

logger = logging.getLogger(__name__)


@dataclass
class CycleResult:
    routes: list[Route] = field(default_factory=list)
    alerted: list[Route] = field(default_factory=list)
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


def run_cycle(session: Session, settings: Settings, scrape: bool = True, notifier=None,
              capital: float | None = None, top_n: int | None = None, max_steps: int | None = None,
              save: bool = True, alert: bool = True) -> CycleResult:
    result = CycleResult()
    if Path(settings.houses_file).exists():
        sync_houses(session, settings.houses_file)
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
                if notifier.send(format_alert(worth, directory, result.routes[0].initial_clp)):
                    now = utcnow()
                    alerted_sigs = {r.signature for r in worth}
                    for row in rows:
                        if row.signature in alerted_sigs:
                            row.alerted, row.alerted_at = True, now
                    result.alerted = worth
        result.expired = expire_old(session, settings.opportunity_ttl_minutes)
    session.flush()
    return result
