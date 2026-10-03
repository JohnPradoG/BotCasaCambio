"""Seguimiento de oportunidades: verificación humana, ejecución y expiración (SPEC §21, §45)."""

from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import ExecutionRow, OpportunityRow, VerificationRow
from app.models.opportunity import OpportunityStatus as S
from app.models.quote import utcnow

logger = logging.getLogger(__name__)

# Transiciones permitidas. Los estados finales pueden corregirse (error de digitación),
# pero siempre queda registro en `verifications`.
ALLOWED: dict[S, set[S]] = {
    S.DETECTED: {S.PENDING_VERIFICATION, S.VERIFIED, S.FAILED, S.EXPIRED, S.EXECUTED, S.PARTIALLY_EXECUTED},
    S.PENDING_VERIFICATION: {S.VERIFIED, S.FAILED, S.EXPIRED, S.EXECUTED, S.PARTIALLY_EXECUTED},
    S.VERIFIED: {S.EXECUTED, S.PARTIALLY_EXECUTED, S.FAILED, S.EXPIRED},
    S.EXPIRED: {S.VERIFIED, S.FAILED, S.EXECUTED, S.PARTIALLY_EXECUTED},
    S.FAILED: {S.VERIFIED, S.EXECUTED, S.PARTIALLY_EXECUTED},
    S.EXECUTED: {S.PARTIALLY_EXECUTED, S.FAILED},
    S.PARTIALLY_EXECUTED: {S.EXECUTED, S.FAILED},
}

MENU = {"1": S.VERIFIED, "2": S.FAILED, "3": S.EXECUTED, "4": S.EXPIRED, "5": S.PARTIALLY_EXECUTED,
        "6": S.PENDING_VERIFICATION}


class InvalidTransition(ValueError):
    pass


def change_status(
    session: Session,
    opportunity_id: int,
    new_status: S | str,
    reason: str | None = None,
    channel: str | None = None,
    final_clp: float | None = None,
    actual_rates: dict | None = None,
) -> OpportunityRow:
    opp = session.get(OpportunityRow, opportunity_id)
    if opp is None:
        raise KeyError(f"oportunidad {opportunity_id} no existe")
    new = S(new_status)
    old = S(opp.status)
    if new != old and new not in ALLOWED[old]:
        raise InvalidTransition(f"no se puede pasar de {old.value} a {new.value}")
    if new in (S.FAILED,) and not reason:
        raise ValueError("indicar la razón del fallo (se usa para el aprendizaje futuro)")
    session.add(VerificationRow(opportunity_id=opp.id, previous_status=old.value, new_status=new.value,
                                reason=reason, channel=channel))
    if new in (S.EXECUTED, S.PARTIALLY_EXECUTED):
        session.add(ExecutionRow(opportunity_id=opp.id, initial_clp=opp.initial_clp, final_clp=final_clp,
                                 actual_rates=actual_rates or {}, notes=reason))
    opp.status = new.value
    opp.status_reason = reason
    opp.last_status_change_at = utcnow()
    session.flush()
    logger.info("Oportunidad #%d: %s → %s (%s)", opp.id, old.value, new.value, reason or "sin razón")
    return opp


def expire_old(session: Session, ttl_minutes: int) -> int:
    """DETECTED / PENDING_VERIFICATION más antiguas que ``ttl_minutes`` pasan a EXPIRED."""
    limit = utcnow() - timedelta(minutes=ttl_minutes)
    rows = session.scalars(
        select(OpportunityRow).where(
            OpportunityRow.status.in_([S.DETECTED.value, S.PENDING_VERIFICATION.value]),
            OpportunityRow.detected_at < limit,
        )
    ).all()
    for opp in rows:
        session.add(VerificationRow(opportunity_id=opp.id, previous_status=opp.status, new_status=S.EXPIRED.value,
                                    reason=f"sin verificar después de {ttl_minutes} min", channel="auto"))
        opp.status = S.EXPIRED.value
        opp.last_status_change_at = utcnow()
    if rows:
        logger.info("%d oportunidades expiradas", len(rows))
    return len(rows)


def list_opportunities(session: Session, status: str | None = None, limit: int = 50) -> list[OpportunityRow]:
    stmt = select(OpportunityRow).order_by(OpportunityRow.detected_at.desc(), OpportunityRow.id.desc()).limit(limit)
    if status:
        stmt = stmt.where(OpportunityRow.status == S(status).value)
    return list(session.scalars(stmt))
