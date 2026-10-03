"""Sistema de cotizaciones: ejecuta scrapers aislados, marca anomalías y guarda TODO el historial."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config.settings import Settings, get_settings
from app.database.models import CurrencyRow, ExchangeHouseRow, QuoteRow, ScraperRunRow
from app.models.quote import NormalizedQuote, QuoteFlag, utcnow
from app.scrapers.base import BaseScraper, ScrapeResult
from app.services.anomaly_service import detect_anomalies
from app.services.house_service import ensure_house

logger = logging.getLogger(__name__)


@dataclass
class CollectionReport:
    results: list[ScrapeResult] = field(default_factory=list)
    saved_quotes: int = 0
    anomalous: list[NormalizedQuote] = field(default_factory=list)

    @property
    def failed(self) -> list[ScrapeResult]:
        return [r for r in self.results if not r.ok]


def recent_peer_mids(session: Session, since_minutes: int) -> dict[str, dict[str, float]]:
    """Último precio medio conocido por (divisa, casa) dentro de la ventana."""
    since = utcnow() - timedelta(minutes=since_minutes)
    rows = session.execute(
        select(QuoteRow.currency, ExchangeHouseRow.slug, QuoteRow.buy_rate, QuoteRow.sell_rate)
        .join(ExchangeHouseRow, QuoteRow.exchange_house_id == ExchangeHouseRow.id)
        .where(QuoteRow.timestamp_collected >= since, QuoteRow.is_anomalous.is_(False))
        .order_by(QuoteRow.timestamp_collected)
    ).all()
    mids: dict[str, dict[str, float]] = {}
    for currency, slug, buy, sell in rows:
        values = [v for v in (buy, sell) if v is not None]
        if values:
            mids.setdefault(currency, {})[slug] = sum(values) / len(values)
    return mids


def save_quote(session: Session, quote: NormalizedQuote, run_id: int | None) -> QuoteRow:
    if session.get(CurrencyRow, quote.currency) is None:
        session.add(CurrencyRow(code=quote.currency))
        logger.info("Nueva divisa detectada: %s", quote.currency)
        session.flush()
    house = ensure_house(session, quote.exchange_house)
    row = QuoteRow(
        exchange_house_id=house.id,
        scraper_run_id=run_id,
        currency=quote.currency,
        quote_currency=quote.quote_currency,
        buy_rate=quote.buy_rate,
        sell_rate=quote.sell_rate,
        timestamp_source=quote.timestamp_source,
        timestamp_collected=quote.timestamp_collected,
        source_url=quote.source_url,
        availability=quote.availability,
        min_amount=quote.min_amount,
        max_amount=quote.max_amount,
        commission_fixed=quote.commission_fixed,
        commission_percent=quote.commission_percent,
        commission_unknown=quote.commission_unknown,
        branch=quote.branch,
        flags=sorted(f.value for f in quote.flags),
        is_anomalous=QuoteFlag.ANOMALOUS_QUOTE in quote.flags,
        notes=quote.notes,
    )
    session.add(row)
    return row


def collect_quotes(session: Session, scrapers: list[BaseScraper], settings: Settings | None = None) -> CollectionReport:
    """Ejecuta cada scraper de forma independiente y persiste resultados y ejecuciones."""
    settings = settings or get_settings()
    report = CollectionReport()
    for scraper in scrapers:
        report.results.append(scraper.run())  # run() nunca lanza

    batch = [q for r in report.results for q in r.quotes]
    peers = recent_peer_mids(session, since_minutes=settings.max_quote_age_minutes * 6)
    report.anomalous = detect_anomalies(
        batch, peers, threshold_percent=settings.anomaly_threshold_percent, min_peers=settings.anomaly_min_peers
    )
    for q in report.anomalous:
        logger.warning("ANOMALOUS_QUOTE %s %s: %s", q.exchange_house, q.currency, q.notes)

    for result in report.results:
        run = ScraperRunRow(
            scraper=result.scraper,
            status=result.status.value,
            started_at=result.started_at,
            finished_at=result.finished_at,
            quotes_count=len(result.quotes),
            rejected_count=len(result.rejected),
            error=result.error,
        )
        session.add(run)
        session.flush()
        for quote in result.quotes:
            save_quote(session, quote, run.id)
            report.saved_quotes += 1
    session.flush()
    logger.info(
        "%d cotizaciones guardadas, %d scrapers fallidos, %d anómalas",
        report.saved_quotes, len(report.failed), len(report.anomalous),
    )
    return report


def latest_quotes(session: Session, max_age_minutes: int | None = None) -> list[QuoteRow]:
    """Última cotización por (casa, divisa, sucursal)."""
    stmt = select(QuoteRow).order_by(QuoteRow.timestamp_collected.desc(), QuoteRow.id.desc())
    if max_age_minutes is not None:
        stmt = stmt.where(QuoteRow.timestamp_collected >= utcnow() - timedelta(minutes=max_age_minutes))
    seen: set[tuple] = set()
    latest: list[QuoteRow] = []
    for row in session.scalars(stmt):
        key = (row.exchange_house_id, row.currency, row.branch)
        if key not in seen:
            seen.add(key)
            latest.append(row)
    return latest
