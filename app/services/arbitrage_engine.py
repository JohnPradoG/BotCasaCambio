"""Motor de arbitraje (Fase 2): grafo de divisas, búsqueda de rutas y cálculo de ganancia.

Regla del proyecto (SPEC §47, §53): el resultado se ordena SOLO por ganancia neta
en CLP. CLP es un nodo más del grafo, así que ``CLP → USD → CLP → EUR → CLP`` es
una ruta válida si deja más CLP.

Grafo
-----
Cada cotización ``(casa, divisa X, compra b, venta s)`` cotizada en CLP genera
dos aristas propias de esa casa (SPEC §8-§9):

* ``CLP → X`` usando ``sell_rate`` (la casa nos VENDE X): ``X = CLP / s``
* ``X → CLP`` usando ``buy_rate``  (la casa nos COMPRA X): ``CLP = X · b``

Una cotización cruzada (p. ej. EUR cotizado en USD) genera aristas USD ↔ EUR de
la misma forma, porque la conversión usa siempre ``quote_currency``.

Búsqueda
--------
Búsqueda por capas (1..MAX_STEPS) con haz (*beam*): en cada paso se conservan los
``SEARCH_BEAM_WIDTH`` mejores estados por divisa. Con conversiones
multiplicativas, un estado con menos dinero en la misma divisa y paso nunca
puede terminar mejor que uno con más dinero que siga el mismo camino, así que el
haz casi no pierde rutas buenas y evita la explosión combinatoria.

Prevención de ciclos (SPEC §12)
-------------------------------
* tope de pasos ``MAX_STEPS``;
* una misma operación (casa + sucursal + origen + destino) no se repite en la ruta;
* volver a una divisa ya visitada solo se permite con MÁS cantidad que la vez
  anterior: un ciclo con pérdida se corta (``CLP → USD → CLP`` con pérdida se
  descarta y no puede usarse como tramo de una ruta más larga);
* rutas con exactamente las mismas operaciones en distinto orden se consideran
  idénticas y se reporta una sola.

Como cada ciclo cerrado tiene que ganar y las operaciones no se repiten, la
búsqueda termina siempre, incluso con un ``MAX_STEPS`` alto.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable, Literal

from app.config.settings import Settings, get_settings
from app.models.quote import NormalizedQuote, QuoteFlag

logger = logging.getLogger(__name__)

Side = Literal["buy", "sell"]


# ---------------------------------------------------------------------- grafo
@dataclass(frozen=True)
class Edge:
    """Una operación posible: cambiar ``from_currency`` por ``to_currency`` en una casa."""

    house: str
    branch: str | None
    from_currency: str
    to_currency: str
    side: Side  # "sell": la casa nos vende to_currency; "buy": la casa nos compra from_currency
    rate: float  # CLP (o quote_currency) por 1 unidad de la divisa cotizada
    quote: NormalizedQuote = field(compare=False, hash=False, repr=False)
    commission_percent: float | None = None
    commission_fixed: float | None = None  # en la moneda de cotización (CLP)
    commission_estimated: bool = False  # True si se usó la comisión manual de .env

    @property
    def key(self) -> tuple:
        return (self.house, self.branch, self.from_currency, self.to_currency)

    def convert(self, amount: float, rate_shift: float = 0.0, with_commission: bool = True) -> float:
        """Cantidad recibida en ``to_currency``.

        ``rate_shift`` empeora la tasa (0.005 = 0,5% peor para el cliente): se usa
        para el margen de seguridad (SPEC §27) y la simulación de §28.
        """
        quote_ccy = self.quote.quote_currency
        fixed = (self.commission_fixed or 0.0) if with_commission else 0.0
        pct = (self.commission_percent or 0.0) if with_commission else 0.0
        if self.side == "sell":
            # pagamos en quote_currency: la comisión fija sale de lo que entregamos
            if self.from_currency == quote_ccy:
                amount -= fixed
            out = amount / (self.rate * (1 + rate_shift))
        else:
            out = amount * self.rate * (1 - rate_shift)
            if self.to_currency == quote_ccy:
                out -= fixed
        return out * (1 - pct / 100)

    def amount_ok(self, amount_in: float, amount_out: float) -> bool:
        """Respeta montos mínimos/máximos publicados (SPEC §15), en unidades de la divisa cotizada."""
        q = self.quote
        if q.min_amount is None and q.max_amount is None:
            return True
        foreign = amount_out if self.side == "sell" else amount_in
        if q.min_amount is not None and foreign < q.min_amount:
            return False
        return q.max_amount is None or foreign <= q.max_amount

    def describe(self) -> str:
        where = f"{self.house}" + (f" ({self.branch})" if self.branch else "")
        return f"{self.from_currency}→{self.to_currency}@{where}"


@dataclass
class CurrencyGraph:
    edges: dict[str, list[Edge]] = field(default_factory=lambda: defaultdict(list))

    @property
    def currencies(self) -> set[str]:
        nodes = set(self.edges)
        for out in self.edges.values():
            nodes.update(e.to_currency for e in out)
        return nodes

    @property
    def edge_count(self) -> int:
        return sum(len(v) for v in self.edges.values())


def build_graph(
    quotes: Iterable[NormalizedQuote],
    default_commission_percent: float | None = None,
    default_commission_fixed: float | None = None,
) -> CurrencyGraph:
    """Crea las aristas del grafo a partir de cotizaciones normalizadas.

    Si una casa no publica comisión (``commission_unknown``), se usa la estimación
    manual de ``.env`` cuando existe y la arista queda marcada como estimada; si
    tampoco hay estimación, se calcula sin comisión y la ruta lo indica.
    """
    graph = CurrencyGraph()
    for q in quotes:
        if q.availability is False:
            # La casa publica que no tiene la divisa: la operación no es ejecutable (SPEC §15).
            logger.info("Sin disponibilidad publicada: %s %s; se omite", q.exchange_house, q.currency)
            continue
        if q.commission_unknown:
            pct, fixed = default_commission_percent, default_commission_fixed
            estimated = pct is not None or fixed is not None
        else:
            pct, fixed, estimated = q.commission_percent, q.commission_fixed, False
        common = dict(house=q.exchange_house, branch=q.branch, quote=q, commission_percent=pct,
                      commission_fixed=fixed, commission_estimated=estimated)
        if q.sell_rate:
            graph.edges[q.quote_currency].append(
                Edge(from_currency=q.quote_currency, to_currency=q.currency, side="sell", rate=q.sell_rate, **common)
            )
        if q.buy_rate:
            graph.edges[q.currency].append(
                Edge(from_currency=q.currency, to_currency=q.quote_currency, side="buy", rate=q.buy_rate, **common)
            )
    return graph


# --------------------------------------------------------------------- rutas
@dataclass
class RouteStep:
    position: int
    house: str
    branch: str | None
    from_currency: str
    to_currency: str
    rate_used: str  # "sell_rate" o "buy_rate"
    rate: float
    amount_in: float
    amount_out: float
    quote_id: int | None
    commission_percent: float | None
    commission_fixed: float | None
    commission_estimated: bool
    commission_unknown: bool
    quote_flags: list[str]
    timestamp_collected: datetime
    quote_age_minutes: float
    availability: bool | None
    branch_used: str | None = None  # sucursal física elegida para este paso (Fase 4)


@dataclass
class Route:
    rank: int | None
    initial_currency: str
    initial_clp: float
    final_clp: float  # CLP final solo con tasas publicadas (bruto)
    gross_profit_clp: float
    commissions_clp: float
    safety_margin_clp: float
    transport_clp: float
    net_profit_clp: float
    profit_percent: float  # sobre la ganancia neta
    steps: int
    route: list[RouteStep]
    houses: list[str]
    currencies: list[str]
    flags: list[str]
    distance_km: float | None = None
    estimated_minutes: float | None = None
    confidence: str | None = None  # HIGH / MEDIUM / LOW
    confidence_score: float | None = None  # 0-100; nunca altera el ranking (SPEC §34)
    executable_now: bool | None = None  # None = horario desconocido
    warnings: list[str] = field(default_factory=list)
    legs: list[dict] = field(default_factory=list)  # tramos de traslado entre sucursales
    trips: int | None = None  # viajes contados para el transporte
    alt_transport: dict | None = None  # {"label", "cost_per_trip", "transport_clp", "net_profit_clp"}
    edges: tuple[Edge, ...] = field(default=(), repr=False)
    stored_signature: str | None = None  # para rutas reconstruidas desde la BD (sin aristas)

    @property
    def net_final_clp(self) -> float:
        return self.initial_clp + self.net_profit_clp

    @property
    def signature(self) -> str:
        if not self.edges and self.stored_signature:
            return self.stored_signature
        return " | ".join(e.describe() for e in self.edges)

    @property
    def requires_verification(self) -> bool:
        return any(f in self.flags for f in (QuoteFlag.ANOMALOUS_QUOTE.value, QuoteFlag.INVERTED_SPREAD.value))

    def to_dict(self) -> dict:
        return {
            "rank": self.rank,
            "initial_clp": self.initial_clp,
            "final_clp": self.final_clp,
            "net_final_clp": self.net_final_clp,
            "gross_profit_clp": self.gross_profit_clp,
            "commissions_clp": self.commissions_clp,
            "safety_margin_clp": self.safety_margin_clp,
            "transport_clp": self.transport_clp,
            "trips": self.trips,
            "alt_transport": self.alt_transport,
            "net_profit_clp": self.net_profit_clp,
            "profit_percent": self.profit_percent,
            "steps": self.steps,
            "distance_km": self.distance_km,
            "estimated_minutes": self.estimated_minutes,
            "confidence": self.confidence,
            "confidence_score": self.confidence_score,
            "executable_now": self.executable_now,
            "warnings": self.warnings,
            "legs": self.legs,
            "route": [s.__dict__ | {"timestamp_collected": s.timestamp_collected.isoformat()} for s in self.route],
            "quotes": [s.quote_id for s in self.route],
            "houses": self.houses,
            "currencies": self.currencies,
            "flags": self.flags,
            "signature": self.signature,
        }


def simulate(edges: Iterable[Edge], amount: float, rate_shift: float = 0.0, with_commission: bool = True) -> float:
    """Aplica una secuencia de operaciones a ``amount``. Devuelve 0 si en algún paso no alcanza."""
    for edge in edges:
        amount = edge.convert(amount, rate_shift, with_commission)
        if amount <= 0:
            return 0.0
    return amount


def sensitivity(route: Route, shifts: Iterable[float] = (0.002, 0.005, 0.01)) -> dict[float, float]:
    """SPEC §28: ganancia (con comisiones, sin margen) si cada tasa empeora en ``shift``."""
    return {s: simulate(route.edges, route.initial_clp, s) - route.initial_clp - route.transport_clp for s in shifts}


@dataclass
class _State:
    currency: str
    amount: float
    edges: tuple[Edge, ...]
    best_seen: dict[str, float]  # mayor cantidad alcanzada por divisa en esta ruta
    used: frozenset


@dataclass
class SearchStats:
    expanded: int = 0
    generated: int = 0
    pruned_losing_cycle: int = 0
    candidate_routes: int = 0
    valid_routes: int = 0


def _quote_age_minutes(q: NormalizedQuote, now: datetime) -> float:
    """Minutos desde el dato más antiguo entre la hora publicada por la casa y la de captura.

    Un precio publicado ayer y leído hace un minuto sigue siendo un precio de ayer.
    Solo afecta la bandera STALE_QUOTE y la confianza, nunca el ranking.
    """
    stamps = [t if t.tzinfo else t.replace(tzinfo=timezone.utc)
              for t in (q.timestamp_collected, q.timestamp_source) if t is not None]
    return max(0.0, (now - min(stamps)).total_seconds() / 60)


def _evaluate(
    edges: tuple[Edge, ...], initial: float, base: str, margin: float,
    now: datetime | None = None, max_quote_age_minutes: float | None = None,
) -> Route:
    now = now or datetime.now(timezone.utc)
    gross_final = simulate(edges, initial, 0.0, with_commission=False)
    after_comm = simulate(edges, initial, 0.0, with_commission=True)
    after_margin = simulate(edges, initial, margin, with_commission=True)
    transport = 0.0  # Fase 4: distance_service
    net_profit = after_margin - transport - initial

    steps: list[RouteStep] = []
    amount = initial
    flags: set[str] = set()
    for i, e in enumerate(edges, start=1):
        out = e.convert(amount)
        q = e.quote
        flags.update(f.value for f in q.flags)
        if q.commission_unknown and not e.commission_estimated:
            flags.add("COMMISSION_UNKNOWN")
        if e.commission_estimated:
            flags.add("COMMISSION_ESTIMATED")
        age = _quote_age_minutes(q, now)
        if max_quote_age_minutes is not None and age > max_quote_age_minutes:
            flags.add("STALE_QUOTE")
        if q.availability is None:
            flags.add("AVAILABILITY_UNKNOWN")
        steps.append(RouteStep(
            position=i, house=e.house, branch=e.branch, from_currency=e.from_currency, to_currency=e.to_currency,
            rate_used="sell_rate" if e.side == "sell" else "buy_rate", rate=e.rate, amount_in=amount,
            amount_out=out, quote_id=q.quote_id, commission_percent=e.commission_percent,
            commission_fixed=e.commission_fixed, commission_estimated=e.commission_estimated,
            commission_unknown=q.commission_unknown, quote_flags=sorted(f.value for f in q.flags),
            timestamp_collected=q.timestamp_collected, quote_age_minutes=age, availability=q.availability,
            branch_used=e.branch,
        ))
        amount = out

    houses: list[str] = []
    for e in edges:
        if not houses or houses[-1] != e.house:
            houses.append(e.house)
    return Route(
        rank=None,
        initial_currency=base,
        initial_clp=initial,
        final_clp=gross_final,
        gross_profit_clp=gross_final - initial,
        commissions_clp=gross_final - after_comm,
        safety_margin_clp=after_comm - after_margin,
        transport_clp=transport,
        net_profit_clp=net_profit,
        profit_percent=net_profit / initial * 100,
        steps=len(edges),
        route=steps,
        houses=houses,
        currencies=[edges[0].from_currency] + [e.to_currency for e in edges],
        flags=sorted(flags),
        edges=edges,
    )


def search_routes(
    graph: CurrencyGraph,
    initial_currency: str = "CLP",
    initial_amount: float = 1_000_000,
    max_steps: int = 5,
    beam_width: int = 100,
    safety_margin_percent: float = 0.0,
    stats: SearchStats | None = None,
    now: datetime | None = None,
    max_quote_age_minutes: float | None = None,
) -> list[Route]:
    """Todas las rutas válidas que empiezan y terminan en ``initial_currency`` con ganancia neta > 0.

    Las cantidades que se comparan durante la búsqueda ya incluyen comisiones y
    margen de seguridad, es decir, el mismo criterio con que se ordena al final.
    """
    stats = stats or SearchStats()
    margin = safety_margin_percent / 100
    frontier = [_State(initial_currency, initial_amount, (), {initial_currency: initial_amount}, frozenset())]
    found: dict[frozenset, Route] = {}

    for _step in range(1, max_steps + 1):
        by_currency: dict[str, list[_State]] = defaultdict(list)
        for st in frontier:
            stats.expanded += 1
            for edge in graph.edges.get(st.currency, ()):
                if edge.key in st.used:
                    continue
                out = edge.convert(st.amount, margin)
                if out <= 0 or not edge.amount_ok(st.amount, out):
                    continue
                previous = st.best_seen.get(edge.to_currency)
                if previous is not None and out <= previous:
                    stats.pruned_losing_cycle += 1
                    continue
                stats.generated += 1
                by_currency[edge.to_currency].append(
                    _State(edge.to_currency, out, st.edges + (edge,), {**st.best_seen, edge.to_currency: out},
                           st.used | {edge.key})
                )
        frontier = []
        for currency, states in by_currency.items():
            states.sort(key=lambda s: s.amount, reverse=True)
            kept = states[:beam_width]
            frontier.extend(kept)
            if currency == initial_currency:
                for st in kept:
                    stats.candidate_routes += 1
                    canonical = frozenset(e.key for e in st.edges)  # mismo conjunto de operaciones = misma ruta
                    if canonical in found:
                        continue
                    route = _evaluate(st.edges, initial_amount, initial_currency, margin, now, max_quote_age_minutes)
                    if route.net_profit_clp > 0:
                        found[canonical] = route
        if not frontier:
            break

    stats.valid_routes = len(found)
    return list(found.values())


def rank_routes(routes: Iterable[Route], top_n: int | None = None) -> list[Route]:
    """Ordena SOLO por ganancia neta (SPEC §4, §34). Empates: menos pasos y luego orden estable."""
    ordered = sorted(routes, key=lambda r: (-r.net_profit_clp, r.steps, r.signature))
    for i, r in enumerate(ordered, start=1):
        r.rank = i
    return ordered[:top_n] if top_n else ordered


def find_best_routes(
    quotes: Iterable[NormalizedQuote],
    initial_currency: str | None = None,
    initial_amount: float | None = None,
    max_steps: int | None = None,
    top_n: int | None = None,
    settings: Settings | None = None,
    stats: SearchStats | None = None,
    directory: dict | None = None,
    distance_provider=None,
    now: datetime | None = None,
) -> list[Route]:
    """Función principal (SPEC §25). Los parámetros omitidos se toman de ``.env``.

    1. arma el grafo y busca todas las rutas con ganancia neta positiva;
    2. toma las ``CANDIDATE_ROUTES`` mejores y les calcula sucursales, distancia,
       tiempo, transporte, horario y confianza (``route_optimizer``);
    3. reordena por ganancia neta (ya con transporte) y devuelve el Top N.

    ``directory`` es ``{slug: ExchangeHouse}`` con sucursales; sin él la distancia
    queda desconocida y la ruta lo indica.
    """
    from app.services.route_optimizer import enrich_routes

    settings = settings or get_settings()
    now = now or datetime.now(timezone.utc)
    quotes = list(quotes)
    graph = build_graph(quotes, settings.default_commission_percent, settings.default_commission_fixed_clp)
    stats = stats if stats is not None else SearchStats()
    routes = search_routes(
        graph,
        initial_currency=initial_currency or settings.base_currency,
        initial_amount=initial_amount if initial_amount is not None else settings.initial_capital_clp,
        max_steps=max_steps or settings.max_steps,
        beam_width=settings.search_beam_width,
        safety_margin_percent=settings.safety_margin_percent,
        stats=stats,
        now=now,
        max_quote_age_minutes=settings.max_quote_age_minutes,
    )
    logger.info(
        "%d cotizaciones, %d divisas, %d aristas; %d rutas generadas, %d rutas válidas",
        len(quotes), len(graph.currencies), graph.edge_count, stats.candidate_routes, stats.valid_routes,
    )
    top_n = top_n or settings.top_routes
    candidates = rank_routes(routes, max(settings.candidate_routes, top_n))
    enriched = enrich_routes(candidates, directory or {}, settings, now=now, provider=distance_provider)
    ranked = rank_routes([r for r in enriched if r.net_profit_clp > 0], top_n)
    logger.info("Top %d calculado", len(ranked))
    return ranked


def reprice_route(
    signature: str,
    quotes: Iterable[NormalizedQuote],
    initial_amount: float,
    settings: Settings | None = None,
    directory: dict | None = None,
    distance_provider=None,
    now: datetime | None = None,
) -> Route | None:
    """Recalcula una ruta ya detectada (misma secuencia de operaciones) con las cotizaciones actuales.

    Devuelve None si alguna operación ya no existe (cotización retirada, sin disponibilidad
    o fuera de los montos publicados). Sirve para avisar cuando la ganancia de una ruta
    alertada baja; no participa del ranking.
    """
    from app.services.route_optimizer import enrich_routes

    settings = settings or get_settings()
    now = now or datetime.now(timezone.utc)
    graph = build_graph(quotes, settings.default_commission_percent, settings.default_commission_fixed_clp)
    index = {e.describe(): e for out in graph.edges.values() for e in out}
    try:
        edges = tuple(index[part] for part in signature.split(" | "))
    except KeyError:
        return None
    amount = initial_amount
    for edge in edges:
        out = edge.convert(amount)
        if out <= 0 or not edge.amount_ok(amount, out):
            return None
        amount = out
    base = edges[0].from_currency
    route = _evaluate(edges, initial_amount, base, settings.safety_margin_percent / 100, now,
                      settings.max_quote_age_minutes)
    return enrich_routes([route], directory or {}, settings, now=now, provider=distance_provider)[0]


__all__ = [
    "Edge", "CurrencyGraph", "Route", "RouteStep", "SearchStats", "build_graph", "search_routes",
    "rank_routes", "find_best_routes", "reprice_route", "simulate", "sensitivity",
]
