"""Precio de referencia del dólar de mercado (USDT/CLP) para comparar con las casas.

No entra al motor de rutas: el USDT no es un billete de dólar y ninguna casa lo cambia.
Sirve para ver cuándo una casa está fuera de mercado (vende el dólar más barato o lo
compra más caro que el mercado) y para mostrarlo en ``/precios`` y en las alertas.

Fuentes, en el orden de ``MARKET_REFERENCE`` (la primera que responda):

* ``binance``: anuncios P2P de USDT/CLP de Binance, filtrados por el monto del capital.
* ``buda``: ticker público de Buda.com (API documentada) para USDT-CLP.

Se respeta robots.txt de cada sitio; si no lo permite o falla, se pasa a la siguiente.
El resultado se guarda unos minutos para no consultar en cada mensaje.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import requests

from app.config.settings import Settings
from app.scrapers.base import _robots_for

logger = logging.getLogger(__name__)

BINANCE_URL = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"
BUDA_URL = "https://www.buda.com/api/v2/markets/usdt-clp/ticker"
CACHE_SECONDS = 300


@dataclass
class MarketRef:
    source: str
    bid: float  # lo que el mercado te paga por 1 USDT (tú vendes)
    ask: float  # lo que pagas por 1 USDT (tú compras)
    url: str
    at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2


def _allowed(url: str, settings: Settings) -> bool:
    if not settings.respect_robots_txt:
        return True
    base = "/".join(url.split("/")[:3])
    parser = _robots_for(base, settings.scraper_user_agent, settings.scraper_timeout_seconds)
    if parser is None:  # robots.txt no se pudo leer: no se consulta
        return False
    return parser.can_fetch(settings.scraper_user_agent, url)


def _binance_side(session: requests.Session, settings: Settings, trade_type: str) -> float | None:
    body = {"asset": "USDT", "fiat": "CLP", "tradeType": trade_type, "page": 1, "rows": 5,
            "payTypes": [], "publisherType": None, "transAmount": str(int(settings.initial_capital_clp))}
    resp = session.post(BINANCE_URL, json=body, timeout=settings.scraper_timeout_seconds,
                        headers={"User-Agent": settings.scraper_user_agent})
    resp.raise_for_status()
    ads = (resp.json() or {}).get("data") or []
    prices = [float(a["adv"]["price"]) for a in ads if a.get("adv", {}).get("price")]
    return prices[0] if prices else None  # el primer anuncio es el mejor precio para ese lado


def from_binance(settings: Settings, session: requests.Session) -> MarketRef | None:
    if not _allowed(BINANCE_URL, settings):
        logger.info("robots.txt de Binance P2P no permite la consulta; se omite")
        return None
    ask = _binance_side(session, settings, "BUY")  # anuncios donde tú compras USDT
    bid = _binance_side(session, settings, "SELL")  # anuncios donde tú vendes USDT
    if ask is None or bid is None:
        return None
    return MarketRef("Binance P2P", bid=bid, ask=ask, url="https://p2p.binance.com/es/trade/all-payments/USDT?fiat=CLP")


def from_buda(settings: Settings, session: requests.Session) -> MarketRef | None:
    if not _allowed(BUDA_URL, settings):
        logger.info("robots.txt de Buda no permite la consulta; se omite")
        return None
    resp = session.get(BUDA_URL, timeout=settings.scraper_timeout_seconds,
                       headers={"User-Agent": settings.scraper_user_agent})
    resp.raise_for_status()
    ticker = (resp.json() or {}).get("ticker") or {}
    try:
        bid, ask = float(ticker["max_bid"][0]), float(ticker["min_ask"][0])
    except (KeyError, IndexError, TypeError, ValueError):
        return None
    return MarketRef("Buda.com", bid=bid, ask=ask, url="https://www.buda.com/chile")


SOURCES = {"binance": from_binance, "buda": from_buda}
_cache: tuple[float, MarketRef | None] | None = None


def get_reference(settings: Settings, session: requests.Session | None = None, use_cache: bool = True) -> MarketRef | None:
    """Precio de mercado del dólar digital, o None si ninguna fuente respondió (nunca se inventa)."""
    global _cache
    if use_cache and _cache and time.monotonic() - _cache[0] < CACHE_SECONDS:
        return _cache[1]
    session = session or requests.Session()
    ref = None
    for name in [s.strip().lower() for s in settings.market_reference.split(",") if s.strip()]:
        source = SOURCES.get(name)
        if source is None:
            logger.warning("MARKET_REFERENCE: fuente desconocida %r", name)
            continue
        try:
            ref = source(settings, session)
        except (requests.RequestException, ValueError) as exc:
            logger.info("Referencia de mercado %s no disponible: %s", name, exc)
            ref = None
        if ref:
            break
    _cache = (time.monotonic(), ref)
    return ref


@dataclass
class Gap:
    house: str
    side: str  # "barato" (la casa vende bajo el mercado) | "caro" (la casa compra sobre el mercado)
    house_price: float
    market_price: float

    @property
    def percent(self) -> float:
        return abs(self.house_price - self.market_price) / self.market_price * 100


def find_gaps(quotes: list, ref: MarketRef, min_percent: float, names: dict[str, str] | None = None) -> list[Gap]:
    """Casas cuyo dólar (USD) está fuera de mercado más allá de ``min_percent``.

    * La casa vende el dólar bajo lo que paga el mercado (``sell_rate < bid``): comprar ahí es barato.
    * La casa compra el dólar sobre lo que cobra el mercado (``buy_rate > ask``): vender ahí paga más.
    """
    names = names or {}
    gaps = []
    for q in quotes:
        if q.currency != "USD":
            continue
        name = names.get(q.exchange_house, q.exchange_house)
        if q.sell_rate is not None and q.sell_rate < ref.bid * (1 - min_percent / 100):
            gaps.append(Gap(name, "barato", q.sell_rate, ref.bid))
        if q.buy_rate is not None and q.buy_rate > ref.ask * (1 + min_percent / 100):
            gaps.append(Gap(name, "caro", q.buy_rate, ref.ask))
    return gaps


def _num(value: float) -> str:
    return f"{value:,.2f}".rstrip("0").rstrip(".").replace(",", "X").replace(".", ",").replace("X", ".")


def reference_line(ref: MarketRef | None) -> str:
    if ref is None:
        return "📈 Dólar de mercado: sin dato ahora."
    return f"📈 Dólar de mercado ({ref.source}, USDT): te pagan {_num(ref.bid)} · te cobran {_num(ref.ask)}"


def gaps_text(gaps: list[Gap]) -> str:
    lines = ["👀 CASA FUERA DE MERCADO (dólar)"]
    for g in gaps:
        if g.side == "barato":
            lines.append(f"• {g.house} vende el dólar a {_num(g.house_price)}, bajo el mercado ({_num(g.market_price)}): "
                         f"{g.percent:.1f}% más barato.")
        else:
            lines.append(f"• {g.house} compra el dólar a {_num(g.house_price)}, sobre el mercado ({_num(g.market_price)}): "
                         f"{g.percent:.1f}% más caro.")
    lines.append("El mercado es el dólar digital (USDT), no billetes. Confirmar precio y stock antes de ir.")
    return "\n".join(lines)
