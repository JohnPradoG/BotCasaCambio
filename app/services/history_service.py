"""Análisis estadístico del historial (SPEC §29, §33). Sin ML: solo datos sólidos."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import timedelta, timezone
from statistics import mean, median
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import ExchangeHouseRow, OpportunityRow, QuoteRow, ScraperRunRow, VerificationRow
from app.models.quote import utcnow


def _aware(dt):
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def best_price_leaders(session: Session, days: int = 30) -> dict[str, dict]:
    """Por divisa: cuántas veces cada casa tuvo la mejor venta (más barata) y la mejor compra (más alta).

    Se compara por ``scraper_run``: cotizaciones obtenidas en la misma ronda.
    """
    since = utcnow() - timedelta(days=days)
    rows = session.execute(
        select(QuoteRow.scraper_run_id, QuoteRow.currency, ExchangeHouseRow.slug, QuoteRow.buy_rate, QuoteRow.sell_rate)
        .join(ExchangeHouseRow, QuoteRow.exchange_house_id == ExchangeHouseRow.id)
        .where(QuoteRow.timestamp_collected >= since, QuoteRow.is_anomalous.is_(False))
    ).all()
    # Agrupar por ronda de recolección y divisa.
    rounds: dict[tuple, list] = defaultdict(list)
    for run_id, cur, slug, buy, sell in rows:
        rounds[(run_id, cur)].append((slug, buy, sell))
    result: dict[str, dict] = defaultdict(lambda: {"best_sell": Counter(), "best_buy": Counter()})
    for (_, cur), items in rounds.items():
        sells = [(s, slug) for slug, _, s in items if s is not None]
        buys = [(b, slug) for slug, b, _ in items if b is not None]
        if len(sells) > 1:
            result[cur]["best_sell"][min(sells)[1]] += 1
        if len(buys) > 1:
            result[cur]["best_buy"][max(buys)[1]] += 1
    return {cur: {k: dict(v) for k, v in d.items()} for cur, d in result.items()}


def opportunity_stats(session: Session, tz: str = "America/Santiago", days: int = 30) -> dict:
    since = utcnow() - timedelta(days=days)
    opps = session.scalars(select(OpportunityRow).where(OpportunityRow.detected_at >= since)).all()
    by_status = Counter(o.status for o in opps)
    by_currency: Counter = Counter()
    by_hour: Counter = Counter()
    zone = ZoneInfo(tz)
    lifetimes: dict[str, list] = defaultdict(list)
    for o in opps:
        for cur in set((o.details or {}).get("currencies", [])) - {"CLP"}:
            by_currency[cur] += 1
        by_hour[_aware(o.detected_at).astimezone(zone).hour] += 1
        if o.signature:
            lifetimes[o.signature].append(_aware(o.detected_at))
    durations = [(max(ts) - min(ts)).total_seconds() / 60 for ts in lifetimes.values() if len(ts) > 1]
    reasons = Counter(
        v.reason for v in session.scalars(select(VerificationRow).where(VerificationRow.new_status == "FAILED"))
        if v.reason
    )
    verified_or_better = sum(by_status[s] for s in ("VERIFIED", "EXECUTED", "PARTIALLY_EXECUTED"))
    checked = verified_or_better + by_status["FAILED"]
    return {
        "total": len(opps),
        "by_status": dict(by_status),
        "by_currency": dict(by_currency.most_common()),
        "by_hour": dict(sorted(by_hour.items())),
        "distinct_routes": len(lifetimes),
        "median_duration_minutes": round(median(durations), 1) if durations else None,
        "real_rate_percent": round(verified_or_better / checked * 100, 1) if checked else None,
        "top_failure_reasons": dict(reasons.most_common(10)),
    }


def source_quality(session: Session, days: int = 30) -> dict[str, dict]:
    """Por scraper: tasa de éxito. Por casa: retraso medio entre la hora publicada y la recolectada."""
    since = utcnow() - timedelta(days=days)
    runs = session.scalars(select(ScraperRunRow).where(ScraperRunRow.started_at >= since)).all()
    scrapers: dict[str, dict] = defaultdict(lambda: {"runs": 0, "ok": 0})
    for r in runs:
        scrapers[r.scraper]["runs"] += 1
        scrapers[r.scraper]["ok"] += r.status in ("OK", "PARTIAL")
    delays: dict[str, list] = defaultdict(list)
    for slug, ts_src, ts_col in session.execute(
        select(ExchangeHouseRow.slug, QuoteRow.timestamp_source, QuoteRow.timestamp_collected)
        .join(ExchangeHouseRow, QuoteRow.exchange_house_id == ExchangeHouseRow.id)
        .where(QuoteRow.timestamp_collected >= since, QuoteRow.timestamp_source.is_not(None))
    ):
        delays[slug].append((_aware(ts_col) - _aware(ts_src)).total_seconds() / 60)
    return {
        "scrapers": {k: {**v, "success_percent": round(v["ok"] / v["runs"] * 100, 1)} for k, v in scrapers.items()},
        "publication_delay_minutes": {k: round(mean(v), 1) for k, v in delays.items()},
    }


def full_report(session: Session, tz: str = "America/Santiago", days: int = 30) -> dict:
    return {
        "opportunities": opportunity_stats(session, tz, days),
        "best_price_leaders": best_price_leaders(session, days),
        "source_quality": source_quality(session, days),
    }
