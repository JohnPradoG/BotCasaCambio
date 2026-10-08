"""Vender cripto publicando un anuncio en P2P (``/p2p``).

En P2P los compradores pagan más que en los exchanges (Buda, Notbank): el anuncio de venta
más barato de Binance P2P suele estar sobre el precio de Buda. Quien publica el anuncio gana
esa diferencia. Para cada cripto se calcula: comprar en el exchange más barato y publicar en
cada plataforma P2P de ``P2P_PUBLISH_VENUES`` un poco bajo el anuncio más barato
(``P2P_UNDERCUT_PERCENT``), para quedar primero en la lista.

Es una ganancia *posible*: solo se cobra si alguien compra al precio publicado, y el precio
puede moverse mientras tanto. Usa las mismas lecturas de ``usdt_spread`` (nunca inventa un
precio). Solo calcula y avisa; nunca publica, compra ni vende.

``/gane`` y ``/ganancias`` anotan lo que John gana de verdad (``P2P_LEDGER_FILE``), para
saber si sirve.
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from app.config.settings import Settings
from app.services.market_reference import MarketRef

logger = logging.getLogger(__name__)

P2P_VENUES = {"binance", "okx", "bybit"}  # plataformas de anuncios entre personas


def _venue(key: str) -> str:
    return key.split(":", 1)[0]


@dataclass
class Plan:
    buy_at: MarketRef  # exchange donde se compra (a su ask)
    publish_on: MarketRef  # plataforma P2P donde se publica
    price: float  # precio sugerido del anuncio
    capital: float
    fee_percent: float  # comisión al comprar en el exchange
    maker_fee_percent: float  # comisión de la plataforma P2P al vender

    @property
    def final_clp(self) -> float:
        units = self.capital * (1 - self.fee_percent / 100) / self.buy_at.ask
        return units * self.price * (1 - self.maker_fee_percent / 100)

    @property
    def profit_clp(self) -> float:
        return self.final_clp - self.capital


def _round_price(price: float) -> float:
    return round(price, 2) if price < 10_000 else float(int(price))


def find_plans(refs: dict[str, MarketRef], settings: Settings) -> list[Plan]:
    """Mejor plan por cripto y plataforma P2P (comprar en el exchange más barato), por ganancia."""
    publish = {v.strip().lower() for v in settings.p2p_publish_venues.split(",") if v.strip()}
    plans = []
    for key, p2p in refs.items():
        if _venue(key) not in publish:
            continue
        exchanges = [r for k, r in refs.items() if _venue(k) not in P2P_VENUES and r.asset == p2p.asset]
        if not exchanges:
            continue
        cheapest = min(exchanges, key=lambda r: r.ask)
        price = _round_price(p2p.ask * (1 - settings.p2p_undercut_percent / 100))
        plans.append(Plan(cheapest, p2p, price, settings.initial_capital_clp, settings.usdt_fee_percent,
                          settings.p2p_maker_fee_percent))
    return sorted(plans, key=lambda p: -p.profit_clp)


def _clp(value: float) -> str:
    sign = "+" if value >= 0 else "−"
    return f"{sign}${abs(value):,.0f}".replace(",", ".")


def _rate(value: float) -> str:
    return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".").removesuffix(",00")


def plan_text(p: Plan) -> str:
    asset = p.buy_at.asset
    fees = "antes de comisiones" if not (p.fee_percent or p.maker_fee_percent) else "con comisiones"
    return "\n".join([
        f"🏷️ PUBLICAR {asset} EN {p.publish_on.source.upper()}",
        f"1) Compra {asset} en {p.buy_at.source} a {_rate(p.buy_at.ask)}",
        f"2) Pásalo a {p.publish_on.source.removesuffix(' P2P')} y publica un anuncio de venta a {_rate(p.price)} "
        f"(el más barato hoy está a {_rate(p.publish_on.ask)})",
        f"Con {_clp(p.capital)[1:]}: {_clp(p.profit_clp)} si te compran todo ({fees}, sin la comisión de retiro).",
        "Ojo: puede tardar en venderse y el precio se puede mover. Libera la cripto solo cuando la plata "
        "esté en tu cuenta.",
        "Cuando vendas, anota lo que ganaste: /gane 15000",
        f"Fuentes: {p.buy_at.url} · {p.publish_on.url}",
    ])


def plans_text(refs: dict[str, MarketRef], settings: Settings) -> str:
    """``/p2p``: el mejor plan de cada cripto que deja ganancia; nunca muestra pérdidas."""
    if not settings.p2p_publish_venues.strip():
        return "El cálculo de anuncios P2P está desactivado (P2P_PUBLISH_VENUES vacío)."
    best: dict[str, Plan] = {}
    for p in find_plans(refs, settings):
        best.setdefault(p.buy_at.asset, p)
    good = [p for p in best.values() if p.profit_clp > 0]
    if not good:
        return "🏷️ Publicar en P2P: sin ganancia por ahora (los anuncios están al precio de los exchanges)."
    return "\n\n".join(plan_text(p) for p in good) + "\n\nSolo calcula; nunca publica, compra ni vende."


def check_p2p_plans(refs: dict[str, MarketRef], settings: Settings, notifier, now: datetime,
                    state: dict[str, datetime]) -> list[str]:
    """Avisa planes con ganancia ≥ ``P2P_MIN_PROFIT_CLP``, cada cripto y plataforma una vez cada
    ``P2P_ALERT_COOLDOWN_HOURS``."""
    sent: list[str] = []
    seen: set[str] = set()
    for p in find_plans(refs, settings):
        key = f"{p.buy_at.asset}:{p.publish_on.source}"
        if key in seen or p.profit_clp <= 0 or p.profit_clp < settings.p2p_min_profit_clp:
            continue
        seen.add(key)
        last = state.get(key)
        if last is not None and now - last < timedelta(hours=settings.p2p_alert_cooldown_hours):
            continue
        if notifier.send(plan_text(p)):
            state[key] = now
            sent.append(key)
            logger.info("Aviso P2P: %s %+.0f CLP", key, p.profit_clp)
    return sent


def morning_due(now_local: datetime, report_time: str | None, last_sent: str | None) -> bool:
    """¿Toca mandar el aviso de la mañana? Una vez al día, desde ``P2P_REPORT_TIME``."""
    return bool(report_time) and now_local.strftime("%H:%M") >= report_time and last_sent != now_local.date().isoformat()


def morning_text(refs: dict[str, MarketRef], settings: Settings) -> str:
    if not refs:
        return "☀️ Buenos días. Hoy no pude leer los precios de las plataformas cripto; prueba /p2p más tarde."
    return "☀️ Buenos días. Para publicar hoy en P2P:\n\n" + plans_text(refs, settings)


# --------------------------------------------------------------- ganancias reales
LEDGER_FIELDS = ["at", "amount_clp", "note"]


def add_gain(path: str | Path, amount: float, note: str, now: datetime) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with path.open("a", newline="") as f:
        writer = csv.writer(f)
        if new:
            writer.writerow(LEDGER_FIELDS)
        writer.writerow([now.isoformat(timespec="seconds"), f"{amount:.0f}", note])


def gains_text(path: str | Path, now: datetime, zone: ZoneInfo) -> str:
    try:
        with Path(path).open(newline="") as f:
            rows = list(csv.DictReader(f))
    except OSError:
        rows = []
    entries = []
    for row in rows:
        try:
            entries.append((datetime.fromisoformat(row["at"]).astimezone(zone), float(row["amount_clp"])))
        except (KeyError, TypeError, ValueError):
            continue
    if not entries:
        return "Todavía no anotas ganancias. Cuando vendas, escribe por ejemplo: /gane 15000"
    local = now.astimezone(zone)
    today = [a for at, a in entries if at.date() == local.date()]
    week = [a for at, a in entries if at >= local - timedelta(days=7)]
    total = [a for _, a in entries]
    return "\n".join([
        "💰 Lo que has ganado (anotado con /gane)",
        f"Hoy: {_clp(sum(today))} en {len(today)} operaciones",
        f"Últimos 7 días: {_clp(sum(week))} en {len(week)} operaciones",
        f"Total: {_clp(sum(total))} en {len(total)} operaciones",
    ])
