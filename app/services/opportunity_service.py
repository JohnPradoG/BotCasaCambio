"""Conecta el motor con la base de datos: carga cotizaciones y guarda rutas/oportunidades."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import OpportunityRow, QuoteRow, RouteRow, RouteStepRow
from app.models.opportunity import OpportunityStatus
from app.models.quote import NormalizedQuote, QuoteFlag, utcnow
from app.services.arbitrage_engine import Route, RouteStep
from app.services.house_service import ensure_house
from app.services.quote_service import latest_quotes

logger = logging.getLogger(__name__)


def row_to_quote(row: QuoteRow) -> NormalizedQuote:
    flags = set()
    for f in row.flags or []:
        try:
            flags.add(QuoteFlag(f))
        except ValueError:
            continue
    return NormalizedQuote(
        exchange_house=row.house.slug,
        currency=row.currency,
        quote_currency=row.quote_currency,
        buy_rate=row.buy_rate,
        sell_rate=row.sell_rate,
        source_url=row.source_url,
        timestamp_source=row.timestamp_source,
        timestamp_collected=row.timestamp_collected,
        availability=row.availability,
        min_amount=row.min_amount,
        max_amount=row.max_amount,
        commission_fixed=row.commission_fixed,
        commission_percent=row.commission_percent,
        branch=row.branch,
        notes=row.notes,
        flags=flags,
        quote_id=row.id,
    )


def quotes_for_engine(session: Session, max_age_minutes: float | None = None,
                      max_published_minutes: float | None = None) -> list[NormalizedQuote]:
    """Última cotización por (casa, divisa, sucursal), lista para el motor.

    Las leídas hace más de ``max_age_minutes`` no se usan para detectar (siguen en el historial).
    La hora publicada por la casa tiene su propio límite, ``max_published_minutes`` (por defecto
    el mismo): un precio publicado hace unos días puede seguir vigente y se usa con aviso, pero
    uno que la página dice haber actualizado hace meses no.
    """
    quotes = [row_to_quote(r) for r in latest_quotes(session, max_age_minutes)]
    if max_age_minutes is None:
        return quotes
    limit = utcnow() - timedelta(minutes=max_published_minutes or max_age_minutes)
    usable = []
    for q in quotes:
        published = q.timestamp_source
        if published is not None and published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        if published is not None and published < limit:
            logger.info("Cotización %s %s%s no usada: publicada %s", q.exchange_house, q.currency,
                        f" ({q.branch})" if q.branch else "", published.isoformat())
            continue
        usable.append(q)
    return usable


def _get_or_create_route(session: Session, route: Route) -> RouteRow:
    signature = route.signature
    row = session.scalar(select(RouteRow).where(RouteRow.signature == signature))
    if row is not None:
        return row
    row = RouteRow(signature=signature, currencies=route.currencies, steps=route.steps)
    for step in route.route:
        house = ensure_house(session, step.house)
        row.route_steps.append(RouteStepRow(
            position=step.position, exchange_house_id=house.id,
            from_currency=step.from_currency, to_currency=step.to_currency,
        ))
    session.add(row)
    session.flush()
    return row


def save_routes(session: Session, routes: list[Route]) -> list[OpportunityRow]:
    """Guarda cada ruta como oportunidad (SPEC §23: se guardan aunque no generen alerta)."""
    saved = []
    for route in routes:
        route_row = _get_or_create_route(session, route)
        status = OpportunityStatus.PENDING_VERIFICATION if route.requires_verification else OpportunityStatus.DETECTED
        opp = OpportunityRow(
            route_id=route_row.id,
            initial_clp=route.initial_clp,
            final_clp=route.final_clp,
            gross_profit_clp=route.gross_profit_clp,
            commissions_clp=route.commissions_clp,
            transport_clp=route.transport_clp,
            safety_margin_clp=route.safety_margin_clp,
            net_profit_clp=route.net_profit_clp,
            profit_percent=route.profit_percent,
            rank=route.rank,
            distance_km=route.distance_km,
            estimated_minutes=route.estimated_minutes,
            confidence=route.confidence,
            status=status.value,
            confidence_score=route.confidence_score,
            executable_now=route.executable_now,
            quote_ids=[s.quote_id for s in route.route if s.quote_id is not None],
            signature=route.signature,
            flags=route.flags,
            last_status_change_at=utcnow(),
            details=route.to_dict(),
        )
        session.add(opp)
        saved.append(opp)
    session.flush()
    logger.info("%d oportunidades guardadas", len(saved))
    return saved


def route_from_row(opp: OpportunityRow) -> Route:
    """Reconstruye la ruta guardada (para mostrarla o generar mensajes de verificación)."""
    d = dict(opp.details or {})
    steps = []
    for raw in d.get("route", []):
        raw = dict(raw)
        raw["timestamp_collected"] = datetime.fromisoformat(raw["timestamp_collected"])
        steps.append(RouteStep(**raw))
    return Route(
        rank=d.get("rank"), initial_currency="CLP", initial_clp=d["initial_clp"], final_clp=d["final_clp"],
        gross_profit_clp=d["gross_profit_clp"], commissions_clp=d["commissions_clp"],
        safety_margin_clp=d["safety_margin_clp"], transport_clp=d["transport_clp"],
        net_profit_clp=d["net_profit_clp"], profit_percent=d["profit_percent"], steps=d["steps"], route=steps,
        houses=d["houses"], currencies=d["currencies"], flags=d.get("flags", []), distance_km=d.get("distance_km"),
        estimated_minutes=d.get("estimated_minutes"), confidence=d.get("confidence"),
        confidence_score=d.get("confidence_score"), executable_now=d.get("executable_now"),
        warnings=d.get("warnings", []), legs=d.get("legs", []), stored_signature=d.get("signature"),
        trips=d.get("trips"), alt_transport=d.get("alt_transport"),
    )
