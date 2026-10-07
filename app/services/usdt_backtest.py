"""Backtesting de la diferencia de USDT entre plataformas (``/backtest``).

Dos fuentes de historia, nunca inventada:

* **Lecturas guardadas** (``USDT_HISTORY_FILE``): cada vez que el bot lee Buda, Binance P2P
  y CryptoMarket guarda su compra/venta. Es la prueba fiel (precios reales de ese momento),
  pero solo cubre desde que el bot empezó a guardarlas.
* **Historia pública** de Buda (operaciones) y CryptoMarket (velas de 15 min) para los días
  anteriores. Es aproximada: son precios a los que alguien operó, no la oferta que había,
  y CryptoMarket no dice de qué lado fue, así que se usa el cierre para comprar y vender.
  Binance, Bybit y OKX P2P no publican historia.

Para cada momento se toma la mejor combinación comprar-en-A / vender-en-B con el capital y
``USDT_FEE_PERCENT``, igual que el aviso. Solo calcula; nunca opera.
"""

from __future__ import annotations

import csv
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from app.config.settings import Settings
from app.services.market_reference import BUDA_URL, CRYPTOMKT_URL, MarketRef, _allowed
from app.services.usdt_spread import Spread, find_spreads

logger = logging.getLogger(__name__)

BUDA_TRADES_URL = BUDA_URL.replace("/ticker", "/trades")
CRYPTOMKT_CANDLES_URL = CRYPTOMKT_URL.replace("/ticker/", "/candles/")
BUCKET = timedelta(minutes=15)
MAX_BUDA_PAGES = 60
FILL_LIMIT = timedelta(hours=1)  # un precio sirve hasta 1 hora si no hay uno más nuevo

Snapshot = tuple[datetime, dict[str, MarketRef]]


def _floor(dt: datetime) -> datetime:
    return dt - timedelta(minutes=dt.minute % 15, seconds=dt.second, microseconds=dt.microsecond)


# ------------------------------------------------------------- lecturas guardadas
def load_recorded(path: str | Path, since: datetime) -> list[Snapshot]:
    """Lecturas guardadas desde ``since``, agrupadas por bloque de 15 minutos."""
    try:
        with Path(path).open(newline="") as f:
            rows = list(csv.DictReader(f))
    except OSError:
        return []
    buckets: dict[datetime, dict[str, MarketRef]] = {}
    for row in rows:
        try:
            at = datetime.fromisoformat(row["at"])
            ref = MarketRef(row["source"], bid=float(row["bid"]), ask=float(row["ask"]), url=row["url"], at=at)
        except (KeyError, TypeError, ValueError):
            continue
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        if at >= since:
            buckets.setdefault(_floor(at), {})[row["venue"]] = ref
    return sorted(buckets.items())


# --------------------------------------------------------------- historia pública
def buda_history(settings: Settings, session: requests.Session, since: datetime) -> dict[datetime, MarketRef]:
    """Por bloque de 15 min: última compra (≈ precio de venta de Buda) y última venta (≈ precio de compra)."""
    if not _allowed(BUDA_TRADES_URL, settings, "buda"):
        return {}
    last: dict[datetime, dict[str, float]] = {}
    cursor = None
    for _ in range(MAX_BUDA_PAGES):
        params = {"limit": 100, **({"timestamp": cursor} if cursor else {})}
        resp = session.get(BUDA_TRADES_URL, params=params, timeout=settings.scraper_timeout_seconds,
                           headers={"User-Agent": settings.scraper_user_agent})
        resp.raise_for_status()
        trades = (resp.json() or {}).get("trades") or {}
        entries = trades.get("entries") or []
        oldest = None
        for entry in entries:  # [timestamp_ms, cantidad, precio, dirección, id], del más nuevo al más viejo
            try:
                at = datetime.fromtimestamp(int(entry[0]) / 1000, tz=timezone.utc)
                price, side = float(entry[2]), str(entry[3])
            except (IndexError, TypeError, ValueError):
                continue
            oldest = at if oldest is None or at < oldest else oldest
            if at >= since:
                last.setdefault(_floor(at), {}).setdefault(side, price)  # el primero visto es el último del bloque
        cursor = trades.get("last_timestamp")
        if not entries or not cursor or (oldest is not None and oldest < since):
            break
        time.sleep(0.5)  # sin apuro: no cargar la API
    refs = {}
    for bucket, sides in last.items():
        if "buy" in sides and "sell" in sides:
            refs[bucket] = MarketRef("Buda.com", bid=sides["sell"], ask=sides["buy"], url="https://www.buda.com/chile",
                                     at=bucket)
    return refs


def cryptomkt_history(settings: Settings, session: requests.Session, since: datetime) -> dict[datetime, MarketRef]:
    """Cierre de cada vela de 15 min (sin lado conocido: se usa para comprar y vender)."""
    if not _allowed(CRYPTOMKT_CANDLES_URL, settings, "cryptomkt"):
        return {}
    params = {"period": "M15", "sort": "DESC", "from": since.isoformat(), "limit": 1000}
    resp = session.get(CRYPTOMKT_CANDLES_URL, params=params, timeout=settings.scraper_timeout_seconds,
                       headers={"User-Agent": settings.scraper_user_agent})
    resp.raise_for_status()
    data = resp.json() or []
    if isinstance(data, dict):  # algunas versiones agrupan por símbolo
        data = next(iter(data.values()), [])
    refs = {}
    for candle in data:
        try:
            at = datetime.fromisoformat(str(candle["timestamp"]).replace("Z", "+00:00"))
            close = float(candle["close"])
        except (KeyError, TypeError, ValueError):
            continue
        if at >= since:
            refs[_floor(at)] = MarketRef("CryptoMarket", bid=close, ask=close, url="https://www.cryptomkt.com/es/", at=at)
    return refs


def merge(histories: dict[str, dict[datetime, MarketRef]]) -> list[Snapshot]:
    """Junta las plataformas por bloque; un precio se mantiene hasta 1 hora si no hay uno nuevo."""
    times = sorted({t for h in histories.values() for t in h})
    current: dict[str, MarketRef] = {}
    snapshots = []
    for t in times:
        for name, h in histories.items():
            if t in h:
                current[name] = h[t]
        live = {n: r for n, r in current.items() if t - _floor(r.at) <= FILL_LIMIT}
        if len(live) >= 2:
            snapshots.append((t, live))
    return snapshots


# ------------------------------------------------------------------- resultado
@dataclass
class Result:
    periods: int
    winners: list[tuple[datetime, Spread]]  # momentos con ganancia (mejor combinación de cada uno)

    @property
    def best(self) -> tuple[datetime, Spread] | None:
        return max(self.winners, key=lambda w: w[1].profit_clp) if self.winners else None


def evaluate(snapshots: list[Snapshot], capital: float, fee_percent: float) -> Result:
    winners = []
    for at, refs in snapshots:
        spreads = [s for s in find_spreads(refs, capital, fee_percent) if s.buy_at is not s.sell_at]
        if spreads and spreads[0].profit_clp > 0:
            winners.append((at, spreads[0]))
    return Result(len(snapshots), winners)


def _clp(value: float) -> str:
    return f"${value:,.0f}".replace(",", ".")


def result_text(title: str, r: Result, zone: ZoneInfo, note: str = "") -> list[str]:
    lines = [title]
    if not r.periods:
        lines.append("Sin datos para comparar (hace falta precio de al menos 2 plataformas a la misma hora).")
        return lines + ([note] if note else [])
    lines.append(f"Momentos revisados (cada 15 min): {r.periods}. Con ganancia: {len(r.winners)}.")
    if r.best:
        at, s = r.best
        pairs: dict[str, int] = {}
        for _, w in r.winners:
            key = f"{w.buy_at.source} → {w.sell_at.source}"
            pairs[key] = pairs.get(key, 0) + 1
        lines.append(f"Mejor: {at.astimezone(zone):%d/%m %H:%M}, comprar en {s.buy_at.source} a {s.buy_at.ask:,.2f} "
                     f"y vender en {s.sell_at.source} a {s.sell_at.bid:,.2f}: +{_clp(s.profit_clp)}")
        avg = sum(w.profit_clp for _, w in r.winners) / len(r.winners)
        lines.append(f"Ganancia promedio cuando hubo: +{_clp(avg)}")
        lines += [f"• {k}: {n} veces" for k, n in sorted(pairs.items(), key=lambda kv: -kv[1])]
    if note:
        lines.append(note)
    return lines


def backtest_text(settings: Settings, days: int, now: datetime | None = None,
                  session: requests.Session | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    zone = ZoneInfo(settings.timezone)
    capital, fee = settings.initial_capital_clp, settings.usdt_fee_percent
    fees = f"comisión {fee:g} % por operación" if fee else "antes de comisiones"
    lines = [f"📈 Backtesting USDT, últimos {days} días, con {_clp(capital)} ({fees})", ""]

    recorded = load_recorded(settings.usdt_history_file, since)
    lines += result_text("1) Precios que guardó el bot (todas las plataformas):", evaluate(recorded, capital, fee),
                         zone, "Esta es la prueba fiel; crece cada día que el bot corre.")
    lines.append("")

    session = session or requests.Session()
    histories, failed = {}, []
    for name, fetch in (("buda", buda_history), ("cryptomkt", cryptomkt_history)):
        try:
            histories[name] = fetch(settings, session, since)
        except Exception as exc:  # noqa: BLE001 - una plataforma rota no detiene a la otra
            logger.info("Historia %s no disponible: %s", name, exc)
            failed.append(name)
    note = "Aproximado: precios de operaciones pasadas, no ofertas. Binance, Bybit y OKX P2P no publican historia."
    if failed:
        note += f" No respondió: {', '.join(failed)}."
    lines += result_text("2) Historia pública Buda vs CryptoMarket:", evaluate(merge(histories), capital, fee), zone, note)
    lines.append("Solo calcula; nunca compra ni vende.")
    return "\n".join(lines)
