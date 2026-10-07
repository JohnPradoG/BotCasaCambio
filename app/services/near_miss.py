"""Qué tan cerca estuvo cada divisa de un arbitraje, aunque no deje ganancia.

Por cada divisa: comprar en la casa que la vende más barata y vender en la que la compra
más cara (CLP → divisa → CLP), con el mismo margen de seguridad que usa el motor. Sirve
para ver con datos si vale la pena bajar márgenes o sumar casas; no cambia las alertas.
El mejor momento de cada divisa en el día se guarda en un JSON para el resumen diario.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class Pair:
    currency: str
    buy_house: str  # donde compras la divisa (venta de la casa)
    buy_price: float
    sell_house: str  # donde la vendes (compra de la casa)
    sell_price: float
    result_clp: float  # CLP ganados (o perdidos) con el capital, después del margen y antes del metro
    at: str = ""  # hora local, solo en el resumen del día

    @property
    def gap_percent(self) -> float:
        return (self.sell_price - self.buy_price) / self.buy_price * 100


def closest_pairs(quotes, capital: float, margin_percent: float, names: dict[str, str] | None = None) -> list[Pair]:
    names = names or {}
    m = margin_percent / 100
    by_currency: dict[str, list] = {}
    for q in quotes:
        if q.currency != "CLP":
            by_currency.setdefault(q.currency, []).append(q)
    pairs = []
    for cur, qs in by_currency.items():
        sells = [q for q in qs if q.sell_rate]
        buys = [q for q in qs if q.buy_rate]
        if not sells or not buys:
            continue
        cheap = min(sells, key=lambda q: q.sell_rate)
        rich = max(buys, key=lambda q: q.buy_rate)
        units = capital / (cheap.sell_rate * (1 + m))
        result = units * rich.buy_rate * (1 - m) - capital
        pairs.append(Pair(cur, names.get(cheap.exchange_house, cheap.exchange_house), cheap.sell_rate,
                          names.get(rich.exchange_house, rich.exchange_house), rich.buy_rate, result))
    pairs.sort(key=lambda p: -p.result_clp)
    return pairs


def _money(value: float) -> str:
    sign = "+" if value >= 0 else "−"
    return f"{sign}${abs(value):,.0f}".replace(",", ".")


def _price(value: float) -> str:
    text = f"{value:,.2f}".rstrip("0").rstrip(".") if value < 100 else f"{value:,.0f}"
    return text.replace(",", "X").replace(".", ",").replace("X", ".")


def _line(p: Pair) -> str:
    when = f" a las {p.at}" if p.at else ""
    return (f"• {p.currency}: comprar en {p.buy_house} a {_price(p.buy_price)} y vender en {p.sell_house} "
            f"a {_price(p.sell_price)} → {_money(p.result_clp)}{when}")


def pairs_text(pairs: list[Pair], capital: float, title: str, limit: int = 8) -> str:
    if not pairs:
        return f"{title}\nNo hay precios suficientes (hace falta una casa que venda y otra que compre la misma divisa)."
    lines = [title, f"Con {_money(capital)[1:]}, después del margen de seguridad y antes del metro:"]
    lines += [_line(p) for p in pairs[:limit]]
    best = pairs[0]
    if best.result_clp > 0:
        lines.append("La primera queda a favor; si no llegó alerta es porque no alcanza el mínimo o el metro se la come.")
    else:
        lines.append(f"Ninguna da ganancia: a la mejor ({best.currency}) le faltan {_money(-best.result_clp)[1:]}.")
    return "\n".join(lines)


def record(path: str | Path, pairs: list[Pair], date: str, hour: str) -> dict:
    """Guarda el mejor resultado del día por divisa. Un día nuevo empieza de cero."""
    path = Path(path)
    try:
        state = json.loads(path.read_text())
    except (OSError, ValueError):
        state = {}
    if state.get("date") != date:
        state = {"date": date, "best": {}}
    for p in pairs:
        prev = state["best"].get(p.currency)
        if prev is None or p.result_clp > prev["result_clp"]:
            state["best"][p.currency] = {**asdict(p), "at": hour}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False))
    return state


def daily_pairs(state: dict) -> list[Pair]:
    pairs = [Pair(**v) for v in (state.get("best") or {}).values()]
    pairs.sort(key=lambda p: -p.result_clp)
    return pairs
