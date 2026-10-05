"""Resumen de los precios guardados para Telegram (``/precios``).

Sin divisa: por cada divisa principal, dónde conviene comprarla (venta más baja de la
casa) y dónde conviene venderla (compra más alta). Con divisa: todas las casas.
Solo muestra precios leídos; no completa ni estima nada.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

MAIN_CURRENCIES = ("USD", "EUR", "BRL", "ARS", "PEN")


@dataclass
class PriceRow:
    house: str
    currency: str
    buy_rate: float | None  # la casa compra la divisa (tú vendes)
    sell_rate: float | None  # la casa vende la divisa (tú compras)
    collected: datetime


def _num(value: float) -> str:
    text = f"{value:,.2f}".rstrip("0").rstrip(".") if value < 100 else f"{value:,.0f}"
    return text.replace(",", "X").replace(".", ",").replace("X", ".")


def _hour(dt: datetime, zone: ZoneInfo) -> str:
    dt = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(zone).strftime("%H:%M")


def currency_detail(rows: list[PriceRow], currency: str, tz: str = "America/Santiago") -> str:
    zone = ZoneInfo(tz)
    rows = [r for r in rows if r.currency == currency]
    if not rows:
        return f"No hay precios guardados de {currency} en las últimas horas."
    rows.sort(key=lambda r: (r.sell_rate is None, r.sell_rate or 0, r.house.lower()))
    lines = [f"💱 {currency}: compra / venta de cada casa"]
    for r in rows:
        buy = _num(r.buy_rate) if r.buy_rate is not None else "—"
        sell = _num(r.sell_rate) if r.sell_rate is not None else "—"
        lines.append(f"• {r.house}: {buy} / {sell} ({_hour(r.collected, zone)})")
    lines.append("Compra = lo que te pagan si vendes. Venta = lo que pagas si compras.")
    return "\n".join(lines)


def overview(rows: list[PriceRow], tz: str = "America/Santiago") -> str:
    if not rows:
        return "No hay precios guardados en las últimas horas."
    houses = sorted({r.house for r in rows})
    lines = [f"💱 Precios de hoy ({len(houses)} casas: {', '.join(houses)})"]
    for cur in MAIN_CURRENCIES:
        cur_rows = [r for r in rows if r.currency == cur]
        if not cur_rows:
            continue
        sells = [r for r in cur_rows if r.sell_rate is not None]
        buys = [r for r in cur_rows if r.buy_rate is not None]
        parts = []
        if sells:
            best = min(sells, key=lambda r: r.sell_rate)
            parts.append(f"comprar en {best.house} a {_num(best.sell_rate)}")
        if buys:
            best = max(buys, key=lambda r: r.buy_rate)
            parts.append(f"vender en {best.house} a {_num(best.buy_rate)}")
        lines.append(f"• {cur}: " + " · ".join(parts))
    others = sorted({r.currency for r in rows} - set(MAIN_CURRENCIES))
    if others:
        lines.append(f"Otras divisas: {', '.join(others)}.")
    lines.append("Detalle por casa: /precios USD (o la divisa que quieras).")
    return "\n".join(lines)


def prices_text(rows: list[PriceRow], currency: str | None = None, tz: str = "America/Santiago") -> str:
    return currency_detail(rows, currency, tz) if currency else overview(rows, tz)
