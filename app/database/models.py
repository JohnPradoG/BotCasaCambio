"""Esquema de base de datos (SQLAlchemy 2.0). Portable entre SQLite y PostgreSQL (SPEC §30).

Todas las tablas del SPEC se crean desde la Fase 1 para que el historial sea
completo desde el primer día; las de rutas/oportunidades se llenan a partir de
la Fase 2. Todos los campos de origen externo son NULLables: un dato desconocido
se guarda como NULL, nunca como un valor supuesto.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.models.quote import utcnow


class Base(DeclarativeBase):
    pass


class ExchangeHouseRow(Base):
    __tablename__ = "exchange_houses"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    website: Mapped[str | None] = mapped_column(String(500))
    quotes_url: Mapped[str | None] = mapped_column(String(500))
    phone: Mapped[str | None] = mapped_column(String(64))
    whatsapp: Mapped[str | None] = mapped_column(String(64))
    source_url: Mapped[str | None] = mapped_column(String(500))
    scraper: Mapped[str | None] = mapped_column(String(64))
    notes: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    branches: Mapped[list["BranchRow"]] = relationship(back_populates="house", cascade="all, delete-orphan")


class BranchRow(Base):
    """Sucursal física: dirección, horario y coordenadas para distancias (Fase 4)."""

    __tablename__ = "branches"
    __table_args__ = (UniqueConstraint("exchange_house_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    exchange_house_id: Mapped[int] = mapped_column(ForeignKey("exchange_houses.id"))
    name: Mapped[str] = mapped_column(String(200))
    address: Mapped[str | None] = mapped_column(String(300))
    comuna: Mapped[str | None] = mapped_column(String(100))
    phone: Mapped[str | None] = mapped_column(String(64))
    whatsapp: Mapped[str | None] = mapped_column(String(64))
    opening_hours: Mapped[str | None] = mapped_column(Text)
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    source_url: Mapped[str | None] = mapped_column(String(500))
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text)

    house: Mapped[ExchangeHouseRow] = relationship(back_populates="branches")


class CurrencyRow(Base):
    __tablename__ = "currencies"

    code: Mapped[str] = mapped_column(String(3), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(100))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ScraperRunRow(Base):
    __tablename__ = "scraper_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    scraper: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    quotes_count: Mapped[int] = mapped_column(Integer, default=0)
    rejected_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)


class QuoteRow(Base):
    """Historial completo de cotizaciones (SPEC §29, §31). Nunca se sobrescribe."""

    __tablename__ = "quotes"
    __table_args__ = (Index("ix_quotes_currency_collected", "currency", "timestamp_collected"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    exchange_house_id: Mapped[int] = mapped_column(ForeignKey("exchange_houses.id"), index=True)
    scraper_run_id: Mapped[int | None] = mapped_column(ForeignKey("scraper_runs.id"))
    currency: Mapped[str] = mapped_column(ForeignKey("currencies.code"))
    quote_currency: Mapped[str] = mapped_column(String(3), default="CLP")
    buy_rate: Mapped[float | None] = mapped_column(Float)
    sell_rate: Mapped[float | None] = mapped_column(Float)
    timestamp_source: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    timestamp_collected: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source_url: Mapped[str] = mapped_column(String(500))
    availability: Mapped[bool | None] = mapped_column(Boolean)
    min_amount: Mapped[float | None] = mapped_column(Float)
    max_amount: Mapped[float | None] = mapped_column(Float)
    commission_fixed: Mapped[float | None] = mapped_column(Float)
    commission_percent: Mapped[float | None] = mapped_column(Float)
    commission_unknown: Mapped[bool] = mapped_column(Boolean, default=True)
    branch: Mapped[str | None] = mapped_column(String(200))
    flags: Mapped[list[str]] = mapped_column(JSON, default=list)
    is_anomalous: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text)

    house: Mapped[ExchangeHouseRow] = relationship()


# --------------------------------------------------------------------------
# Tablas que se llenan desde la Fase 2 en adelante.
# --------------------------------------------------------------------------


class RouteRow(Base):
    __tablename__ = "routes"

    id: Mapped[int] = mapped_column(primary_key=True)
    signature: Mapped[str] = mapped_column(String(500), index=True)  # p. ej. "CLP>USD@afex|USD>CLP@x"
    currencies: Mapped[list[str]] = mapped_column(JSON)
    steps: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    route_steps: Mapped[list["RouteStepRow"]] = relationship(back_populates="route", cascade="all, delete-orphan")


class RouteStepRow(Base):
    __tablename__ = "route_steps"

    id: Mapped[int] = mapped_column(primary_key=True)
    route_id: Mapped[int] = mapped_column(ForeignKey("routes.id"))
    position: Mapped[int] = mapped_column(Integer)
    exchange_house_id: Mapped[int] = mapped_column(ForeignKey("exchange_houses.id"))
    branch_id: Mapped[int | None] = mapped_column(ForeignKey("branches.id"))
    from_currency: Mapped[str] = mapped_column(String(3))
    to_currency: Mapped[str] = mapped_column(String(3))

    route: Mapped[RouteRow] = relationship(back_populates="route_steps")


class OpportunityRow(Base):
    __tablename__ = "opportunities"

    id: Mapped[int] = mapped_column(primary_key=True)
    route_id: Mapped[int] = mapped_column(ForeignKey("routes.id"))
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    initial_clp: Mapped[float] = mapped_column(Float)
    final_clp: Mapped[float] = mapped_column(Float)
    gross_profit_clp: Mapped[float] = mapped_column(Float)
    commissions_clp: Mapped[float] = mapped_column(Float, default=0)
    transport_clp: Mapped[float] = mapped_column(Float, default=0)
    safety_margin_clp: Mapped[float] = mapped_column(Float, default=0)
    net_profit_clp: Mapped[float] = mapped_column(Float, index=True)
    profit_percent: Mapped[float] = mapped_column(Float)
    rank: Mapped[int | None] = mapped_column(Integer)
    distance_km: Mapped[float | None] = mapped_column(Float)
    estimated_minutes: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[str | None] = mapped_column(String(16))
    confidence_score: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(32), default="DETECTED", index=True)
    executable_now: Mapped[bool | None] = mapped_column(Boolean)
    quote_ids: Mapped[list[int]] = mapped_column(JSON, default=list)  # tasas exactas usadas
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    alerted: Mapped[bool] = mapped_column(Boolean, default=False)


class VerificationRow(Base):
    __tablename__ = "verifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    opportunity_id: Mapped[int] = mapped_column(ForeignKey("opportunities.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    previous_status: Mapped[str] = mapped_column(String(32))
    new_status: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str | None] = mapped_column(Text)
    channel: Mapped[str | None] = mapped_column(String(32))  # phone, whatsapp, in_person


class ExecutionRow(Base):
    __tablename__ = "executions"

    id: Mapped[int] = mapped_column(primary_key=True)
    opportunity_id: Mapped[int] = mapped_column(ForeignKey("opportunities.id"), index=True)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    initial_clp: Mapped[float | None] = mapped_column(Float)
    final_clp: Mapped[float | None] = mapped_column(Float)
    actual_rates: Mapped[dict] = mapped_column(JSON, default=dict)
    notes: Mapped[str | None] = mapped_column(Text)


class TransportCostRow(Base):
    __tablename__ = "transport_costs"

    id: Mapped[int] = mapped_column(primary_key=True)
    mode: Mapped[str] = mapped_column(String(32), unique=True)  # walk, public_transport, car, taxi
    cost_per_km_clp: Mapped[float] = mapped_column(Float)
    fixed_cost_clp: Mapped[float] = mapped_column(Float, default=0)
    speed_kmh: Mapped[float | None] = mapped_column(Float)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
