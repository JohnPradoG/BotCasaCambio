"""Panel web y API (SPEC §39). Sencillo a propósito: primero funcionalidad.

    python -m app.main dashboard   →   http://127.0.0.1:8000
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Iterator

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config.settings import Settings, get_settings
from app.database.db import init_db, session_scope
from app.database.models import OpportunityRow
from app.models.opportunity import OpportunityStatus
from app.notifications.messages import verification_messages
from app.services.cycle_service import run_cycle
from app.services.history_service import full_report
from app.services.house_service import house_directory, house_stats
from app.services.opportunity_service import route_from_row
from app.services.quote_service import latest_quotes
from app.services.verification_service import InvalidTransition, change_status, list_opportunities

STATIC = Path(__file__).parent / "static"



@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="BotCasaCambio", description="Detección de arbitraje entre casas de cambio (solo alerta)",
              lifespan=lifespan)


def settings_dep() -> Settings:
    return get_settings()


def db() -> Iterator[Session]:
    with session_scope() as s:
        yield s


def auth(token: str | None = Query(None), x_token: str | None = Header(None), settings: Settings = Depends(settings_dep)):
    if settings.dashboard_token and settings.dashboard_token not in (token, x_token):
        raise HTTPException(status_code=401, detail="token inválido")


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def index() -> str:
    return (STATIC / "index.html").read_text(encoding="utf-8")


@app.get("/api/top", dependencies=[Depends(auth)])
def top(capital: float | None = None, steps: int | None = None, top: int | None = None,
        session: Session = Depends(db), settings: Settings = Depends(settings_dep)) -> dict:
    """Top N calculado en el momento con las cotizaciones guardadas (no guarda ni alerta)."""
    result = run_cycle(session, settings, scrape=False, capital=capital, top_n=top, max_steps=steps,
                       save=False, alert=False)
    return {
        "initial_clp": capital or settings.initial_capital_clp,
        "quotes_used": result.quotes_used,
        "routes_generated": result.stats.candidate_routes,
        "routes_valid": result.stats.valid_routes,
        "routes": [r.to_dict() for r in result.routes],
    }


@app.get("/api/quotes", dependencies=[Depends(auth)])
def quotes(max_age: int | None = None, session: Session = Depends(db)) -> list[dict]:
    return [
        {"id": q.id, "house": q.house.slug, "currency": q.currency, "buy_rate": q.buy_rate, "sell_rate": q.sell_rate,
         "timestamp_collected": q.timestamp_collected.isoformat(), "source_url": q.source_url, "flags": q.flags,
         "availability": q.availability, "commission_unknown": q.commission_unknown}
        for q in latest_quotes(session, max_age)
    ]


@app.get("/api/houses", dependencies=[Depends(auth)])
def houses(session: Session = Depends(db), settings: Settings = Depends(settings_dep)) -> dict:
    stats = house_stats(session, settings.max_quote_age_minutes)
    return {
        "discovered": stats.discovered,
        "with_active_quotes": stats.with_active_quotes,
        "unavailable": stats.unavailable,
        "houses": [
            {"slug": h.slug, "name": h.name, "website": h.website, "phone": h.phone, "whatsapp": h.whatsapp,
             "branches": [b.__dict__ for b in h.branches]}
            for h in house_directory(session).values()
        ],
    }


def _opp_dict(o: OpportunityRow) -> dict:
    d = o.details or {}
    return {
        "id": o.id, "detected_at": o.detected_at.isoformat(), "status": o.status, "status_reason": o.status_reason,
        "net_profit_clp": o.net_profit_clp, "gross_profit_clp": o.gross_profit_clp, "initial_clp": o.initial_clp,
        "confidence": o.confidence, "confidence_score": o.confidence_score, "executable_now": o.executable_now,
        "distance_km": o.distance_km, "estimated_minutes": o.estimated_minutes, "currencies": d.get("currencies", []),
        "houses": d.get("houses", []), "flags": o.flags, "alerted": o.alerted,
    }


@app.get("/api/opportunities", dependencies=[Depends(auth)])
def opportunities(status: OpportunityStatus | None = None, limit: int = 100, session: Session = Depends(db)) -> list[dict]:
    return [_opp_dict(o) for o in list_opportunities(session, status.value if status else None, limit)]


@app.get("/api/opportunities/{opp_id}", dependencies=[Depends(auth)])
def opportunity(opp_id: int, session: Session = Depends(db)) -> dict:
    o = session.get(OpportunityRow, opp_id)
    if o is None:
        raise HTTPException(404, "no existe")
    route = route_from_row(o)
    return {**_opp_dict(o), "route": route.to_dict(),
            "verification_messages": verification_messages(route, house_directory(session))}


class StatusChange(BaseModel):
    status: OpportunityStatus
    reason: str | None = None
    channel: str | None = "web"
    final_clp: float | None = None


@app.post("/api/opportunities/{opp_id}/status", dependencies=[Depends(auth)])
def set_status(opp_id: int, body: StatusChange, session: Session = Depends(db)) -> dict:
    try:
        o = change_status(session, opp_id, body.status, body.reason, body.channel, body.final_clp)
    except KeyError:
        raise HTTPException(404, "no existe")
    except (InvalidTransition, ValueError) as exc:
        raise HTTPException(400, str(exc))
    return _opp_dict(o)


@app.get("/api/stats", dependencies=[Depends(auth)])
def stats(days: int = 30, session: Session = Depends(db), settings: Settings = Depends(settings_dep)) -> dict:
    return full_report(session, settings.timezone, days)
