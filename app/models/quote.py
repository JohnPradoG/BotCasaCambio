"""Cotización normalizada: el único formato que los scrapers pueden devolver.

Convención (SPEC §8), siempre desde el punto de vista de la CASA y en CLP por 1 unidad:

* ``buy_rate``  = precio al que la casa COMPRA la divisa al cliente.
  Se usa cuando el cliente tiene divisa y quiere CLP (X -> CLP).
* ``sell_rate`` = precio al que la casa VENDE la divisa al cliente.
  Se usa cuando el cliente tiene CLP y quiere divisa (CLP -> X).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum


class QuoteFlag(str, Enum):
    ANOMALOUS_QUOTE = "ANOMALOUS_QUOTE"  # muy lejos de las demás casas (SPEC §35)
    INVERTED_SPREAD = "INVERTED_SPREAD"  # compra > venta: posible error de publicación o etiquetas invertidas
    MISSING_BUY = "MISSING_BUY"
    MISSING_SELL = "MISSING_SELL"
    AUTO_DISCOVERED = "AUTO_DISCOVERED"  # leída por el descubrimiento automático, sin scraper dedicado


class QuoteValidationError(ValueError):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class NormalizedQuote:
    exchange_house: str  # slug de la casa (ver data/exchange_houses.json)
    currency: str  # ISO 4217
    buy_rate: float | None
    sell_rate: float | None
    source_url: str
    quote_currency: str = "CLP"
    timestamp_source: datetime | None = None  # hora publicada por la casa, si existe
    timestamp_collected: datetime = field(default_factory=utcnow)
    availability: bool | None = None  # None = no publicado
    min_amount: float | None = None
    max_amount: float | None = None
    commission_fixed: float | None = None
    commission_percent: float | None = None
    branch: str | None = None  # si la cotización aplica solo a una sucursal
    notes: str | None = None
    flags: set[QuoteFlag] = field(default_factory=set)
    quote_id: int | None = None  # id en la tabla quotes, cuando viene de la BD

    @property
    def commission_unknown(self) -> bool:
        return self.commission_fixed is None and self.commission_percent is None

    @property
    def mid_rate(self) -> float | None:
        if self.buy_rate is not None and self.sell_rate is not None:
            return (self.buy_rate + self.sell_rate) / 2
        return self.buy_rate if self.buy_rate is not None else self.sell_rate

    def validate(self) -> "NormalizedQuote":
        """Valida coherencia básica. Lanza QuoteValidationError si el dato es inutilizable."""
        if not self.exchange_house:
            raise QuoteValidationError("exchange_house vacío")
        if not (isinstance(self.currency, str) and len(self.currency) == 3 and self.currency.isalpha()):
            raise QuoteValidationError(f"código de divisa inválido: {self.currency!r}")
        self.currency = self.currency.upper()
        self.quote_currency = self.quote_currency.upper()
        if self.currency == self.quote_currency:
            raise QuoteValidationError(f"divisa igual a la moneda de cotización: {self.currency}")
        if not self.source_url:
            raise QuoteValidationError("source_url es obligatorio (trazabilidad del dato)")
        if self.buy_rate is None and self.sell_rate is None:
            raise QuoteValidationError(f"{self.exchange_house} {self.currency}: sin precio de compra ni de venta")
        for name in ("buy_rate", "sell_rate"):
            value = getattr(self, name)
            if value is not None and not value > 0:
                raise QuoteValidationError(f"{name} debe ser > 0, recibido {value!r}")
        if self.buy_rate is None:
            self.flags.add(QuoteFlag.MISSING_BUY)
        if self.sell_rate is None:
            self.flags.add(QuoteFlag.MISSING_SELL)
        # No intercambiamos automáticamente: lo marcamos para verificación humana.
        if self.buy_rate is not None and self.sell_rate is not None and self.buy_rate > self.sell_rate:
            self.flags.add(QuoteFlag.INVERTED_SPREAD)
        if self.min_amount is not None and self.max_amount is not None and self.min_amount > self.max_amount:
            raise QuoteValidationError("min_amount > max_amount")
        if self.timestamp_collected.tzinfo is None:
            self.timestamp_collected = self.timestamp_collected.replace(tzinfo=timezone.utc)
        return self

    def to_dict(self) -> dict:
        data = asdict(self)
        data["flags"] = sorted(f.value for f in self.flags)
        data["commission_unknown"] = self.commission_unknown
        for key in ("timestamp_source", "timestamp_collected"):
            if data[key] is not None:
                data[key] = data[key].isoformat()
        return data
