"""Diferencia de precio de criptomonedas entre plataformas (USDT, BTC, ETH, USDC…).

Para cada cripto de ``CRYPTO_ASSETS`` y cada plataforma de ``USDT_VENUES``: si una plataforma
la vende (``ask``) más barata de lo que otra la compra (``bid``),
comprar en la primera y vender en la segunda deja ganancia. Se calcula con el capital
configurado y la comisión ``USDT_FEE_PERCENT`` por operación (0 por defecto: el aviso dice
que es antes de comisiones). Solo detecta y avisa; nunca opera.

Usa los mismos lectores de ``market_reference`` (respetan robots.txt). Si una plataforma
no responde, simplemente no se compara; nunca se inventa un precio.
"""

from __future__ import annotations

import csv
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import requests

from app.config.settings import Settings
from app.services.market_reference import SOURCES, MarketRef

logger = logging.getLogger(__name__)
CACHE_SECONDS = 300
_cache: tuple[float, dict[str, MarketRef]] | None = None


def assets(settings: Settings) -> list[str]:
    return [a.strip().upper() for a in settings.crypto_assets.split(",") if a.strip()] or ["USDT"]


def ref_key(venue: str, asset: str) -> str:
    """Clave de una lectura: ``buda`` para USDT (como antes), ``buda:BTC`` para las demás."""
    return venue if asset == "USDT" else f"{venue}:{asset}"


def fetch_all(settings: Settings, session: requests.Session | None = None, use_cache: bool = True) -> dict[str, MarketRef]:
    """Precio de cada cripto en cada plataforma de ``USDT_VENUES`` que respondió."""
    global _cache
    if use_cache and _cache and time.monotonic() - _cache[0] < CACHE_SECONDS:
        return _cache[1]
    session = session or requests.Session()
    refs: dict[str, MarketRef] = {}
    for name in [s.strip().lower() for s in settings.usdt_venues.split(",") if s.strip()]:
        source = SOURCES.get(name)
        if source is None:
            logger.warning("USDT_VENUES: plataforma desconocida %r", name)
            continue
        for asset in assets(settings):
            try:
                ref = source(settings, session, asset)
            except Exception as exc:  # noqa: BLE001 - una plataforma rota no detiene a las demás
                logger.info("%s en %s no disponible: %s", asset, name, exc)
                continue
            if ref:
                refs[ref_key(name, asset)] = ref
    _cache = (time.monotonic(), refs)
    record(settings.usdt_history_file, refs)
    return refs


HISTORY_FIELDS = ["at", "venue", "source", "bid", "ask", "url"]


def record(path: str | Path, refs: dict[str, MarketRef]) -> None:
    """Agrega cada lectura al historial (CSV) para el backtesting. Si falla, solo se avisa en el log."""
    if not path or not refs:
        return
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        new = not path.exists()
        with path.open("a", newline="") as f:
            writer = csv.writer(f)
            if new:
                writer.writerow(HISTORY_FIELDS)
            for name, r in refs.items():
                writer.writerow([r.at.isoformat(timespec="seconds"), name, r.source, r.bid, r.ask, r.url])
    except OSError as exc:
        logger.warning("No se pudo guardar el historial USDT: %s", exc)


@dataclass
class Spread:
    buy_at: MarketRef  # donde compras USDT (a su ask)
    sell_at: MarketRef  # donde lo vendes (a su bid)
    capital: float
    fee_percent: float

    @property
    def final_clp(self) -> float:
        f = self.fee_percent / 100
        return self.capital * (1 - f) / self.buy_at.ask * self.sell_at.bid * (1 - f)

    @property
    def profit_clp(self) -> float:
        return self.final_clp - self.capital


def find_spreads(refs: dict[str, MarketRef], capital: float, fee_percent: float) -> list[Spread]:
    """Combinaciones comprar-en-A / vender-en-B de la misma cripto (también A=B), por ganancia."""
    spreads = [Spread(a, b, capital, fee_percent) for a in refs.values() for b in refs.values()
               if a.asset == b.asset]
    return sorted(spreads, key=lambda s: -s.profit_clp)


def _clp(value: float) -> str:
    sign = "+" if value >= 0 else "−"
    return f"{sign}${abs(value):,.0f}".replace(",", ".")


def _rate(value: float) -> str:
    return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def spread_text(s: Spread) -> str:
    fees = f"con comisión {s.fee_percent:g} % por operación" if s.fee_percent else "antes de comisiones"
    asset = s.buy_at.asset
    lines = [
        f"💱 DIFERENCIA {asset} ENTRE PLATAFORMAS",
        f"Comprar {asset} en {s.buy_at.source} a {_rate(s.buy_at.ask)}",
        f"Venderlo en {s.sell_at.source} a {_rate(s.sell_at.bid)}",
        f"Con {_clp(s.capital)[1:]}: {_clp(s.profit_clp)} ({fees}).",
    ]
    if s.buy_at.source != s.sell_at.source:
        lines.append(f"Ojo: pasar {asset} de una plataforma a otra cobra comisión de retiro y puede tardar.")
    lines += ["Ojo: en P2P revisa la reputación del comprador y que el pago llegue antes de liberar.",
              f"Fuentes: {s.buy_at.url} · {s.sell_at.url}"]
    return "\n".join(lines)


def venues_text(refs: dict[str, MarketRef], settings: Settings) -> str:
    """``/usdt``: precio de cada cripto en cada plataforma, cuáles no respondieron y la mejor diferencia."""
    names = [s.strip().lower() for s in settings.usdt_venues.split(",") if s.strip()]
    if not names:
        return "La comparación de cripto está desactivada (USDT_VENUES vacío)."
    lines = ["💱 Cripto en pesos ahora (compras a / vendes a)"]
    for asset in assets(settings):
        lines += ["", f"{asset}:"]
        for name in names:
            r = refs.get(ref_key(name, asset))
            lines.append(f"✅ {r.source}: {_rate(r.ask)} / {_rate(r.bid)}" if r else f"❌ {name}: no respondió")
        best = next((s for s in find_spreads({k: r for k, r in refs.items() if r.asset == asset},
                                             settings.initial_capital_clp, settings.usdt_fee_percent)
                     if s.buy_at is not s.sell_at), None)
        if best:
            lines.append(f"Mejor: comprar en {best.buy_at.source} y vender en {best.sell_at.source}: "
                         f"{_clp(best.profit_clp)} con {_clp(best.capital)[1:]}")
    return "\n".join(lines)


def check_usdt_spreads(refs: dict[str, MarketRef], settings: Settings, notifier, now: datetime,
                       state: dict[str, datetime]) -> list[str]:
    """Avisa la mejor diferencia con ganancia > ``MIN_NET_PROFIT_CLP``, una vez cada ``USDT_ALERT_COOLDOWN_HOURS``."""
    best = next(iter(find_spreads(refs, settings.initial_capital_clp, settings.usdt_fee_percent)), None)
    if best is None or best.profit_clp <= max(settings.min_net_profit_clp, 0):
        return []
    key = f"{best.buy_at.asset}:{best.buy_at.source}>{best.sell_at.source}"
    last = state.get(key)
    if last is not None and now - last < timedelta(hours=settings.usdt_alert_cooldown_hours):
        return []
    if not notifier.send(spread_text(best)):
        return []
    state[key] = now
    logger.info("Aviso cripto: %s %+.0f CLP", key, best.profit_clp)
    return [key]
