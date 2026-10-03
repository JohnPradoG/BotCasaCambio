"""Convierte una ruta de divisas en un recorrido físico (Fase 4).

Para cada ruta:

1. agrupa pasos consecutivos en la misma casa (una sola visita);
2. elige la sucursal de cada visita que minimiza la distancia total (programación
   dinámica sobre las sucursales con coordenadas);
3. calcula tramos, km, minutos (traslado + atención), costo de transporte y lo
   descuenta de la ganancia neta (SPEC §17, §26);
4. revisa horarios: si una casa está cerrada la ruta NO es ejecutable ahora,
   pero se mantiene como oportunidad (SPEC §37);
5. calcula la confianza (SPEC §19, §34), que nunca altera el ranking.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.config.settings import Settings
from app.models.exchange_house import Branch, ExchangeHouse
from app.services import confidence_service
from app.services.arbitrage_engine import Route
from app.services.distance_service import DistanceProvider, make_provider, transport_cost
from app.services.schedule_service import open_during


@dataclass
class _Stop:
    house: str
    step_indexes: list[int]
    candidates: list[Branch]


def _stops(route: Route, directory: dict[str, ExchangeHouse]) -> list[_Stop]:
    stops: list[_Stop] = []
    for i, step in enumerate(route.route):
        quote_branch = route.edges[i].branch if route.edges else step.branch
        if stops and stops[-1].house == step.house and (quote_branch is None or
                                                        quote_branch in [b.name for b in stops[-1].candidates]):
            stops[-1].step_indexes.append(i)
            if quote_branch:
                stops[-1].candidates = [b for b in stops[-1].candidates if b.name == quote_branch]
            continue
        house = directory.get(step.house)
        branches = list(house.branches) if house else []
        if quote_branch:
            branches = [b for b in branches if b.name == quote_branch]
        stops.append(_Stop(step.house, [i], branches))
    return stops


def _coords(b: Branch) -> tuple[float, float] | None:
    if b.latitude is None or b.longitude is None:
        return None
    return (b.latitude, b.longitude)


def _choose_branches(stops: list[_Stop], provider: DistanceProvider, origin) -> tuple[list[Branch | None], list, bool]:
    """Devuelve (sucursal por visita, tramos, distancia_conocida)."""
    located = [[b for b in s.candidates if _coords(b)] for s in stops]
    if not stops or any(not opts for opts in located):
        # Sin coordenadas para alguna visita: distancia desconocida. Se usa la primera
        # sucursal conocida solo para mostrar dirección/horario.
        return [s.candidates[0] if s.candidates else None for s in stops], [], False

    # DP: best[j][k] = (km acumulados, tramos) llegando a la sucursal k de la visita j.
    prev: list[tuple[float, list]] = []
    for b in located[0]:
        if origin:
            leg = provider.leg(origin, _coords(b))
            prev.append((leg.km, [("origen", b, leg, 0)]))
        else:
            prev.append((0.0, []))
    choice = [[i] for i in range(len(located[0]))]
    for j in range(1, len(stops)):
        cur, cur_choice = [], []
        for b in located[j]:
            best = None
            for k, a in enumerate(located[j - 1]):
                leg = provider.leg(_coords(a), _coords(b)) if a is not b else None
                km = prev[k][0] + (leg.km if leg else 0.0)
                if best is None or km < best[0]:
                    legs = prev[k][1] + ([(a.name, b, leg, j)] if leg and leg.km > 0 else [])
                    best = (km, legs, k)
            cur.append((best[0], best[1]))
            cur_choice.append(choice[best[2]] + [located[j].index(b)])
        prev, choice = cur, cur_choice
    end = min(range(len(prev)), key=lambda k: prev[k][0])
    chosen = [located[j][idx] for j, idx in enumerate(choice[end])]
    return chosen, prev[end][1], True


def enrich_routes(
    routes: list[Route],
    directory: dict[str, ExchangeHouse],
    settings: Settings,
    now: datetime | None = None,
    provider: DistanceProvider | None = None,
) -> list[Route]:
    now = now or datetime.now(timezone.utc)
    provider = provider or make_provider(settings)
    origin = (settings.origin_lat, settings.origin_lon) if settings.origin_lat is not None and settings.origin_lon is not None else None

    for route in routes:
        stops = _stops(route, directory)
        chosen, legs, known = _choose_branches(stops, provider, origin)
        flags = set(route.flags)

        for stop, branch in zip(stops, chosen):
            for i in stop.step_indexes:
                route.route[i].branch_used = branch.name if branch else route.route[i].branch

        home = settings.transport_from_home
        if known:
            trip_legs = list(legs)
            if home and origin and chosen:
                # Vuelta a casa desde la última sucursal (cuenta en km y costo, no en el horario).
                trip_legs.append((chosen[-1].name, "origen", provider.leg(_coords(chosen[-1]), origin), None))
            km = sum(leg.km for _, _, leg, _ in trip_legs)
            travel_min = sum(leg.minutes for _, _, leg, _ in trip_legs)
            route.distance_km = round(km, 2)
            route.legs = [
                {"from": a, "to": b if isinstance(b, str) else b.name, "km": round(leg.km, 2),
                 "minutes": round(leg.minutes, 1), "source": leg.source}
                for a, b, leg, _ in trip_legs
            ]
            between = sum(1 for a, *_ in legs if a != "origen")
            trips = between + 2 if home else len(trip_legs)
            route.transport_clp = transport_cost(km, trips, settings)
            route.trips = trips
        else:
            travel_min = None
            route.distance_km = None
            route.legs = []
            # Sin coordenadas no hay km, pero sí se sabe cuántos viajes hay: un pasaje por cada
            # cambio de casa, más la ida y la vuelta si se sale desde casa.
            trips = max(len(stops) - 1, 0) + (2 if home else 0)
            route.transport_clp = transport_cost(0.0, trips, settings)
            route.trips = trips
            flags.add("DISTANCE_UNKNOWN")

        service_min = route.steps * settings.minutes_per_operation
        route.estimated_minutes = None if travel_min is None else round(travel_min + service_min, 1)

        # Horario: se recorre la ruta en el tiempo (con traslado si se conoce).
        t = now
        legs_by_stop = {j: leg for _, _, leg, j in legs}
        states = []
        for j, (stop, branch) in enumerate(zip(stops, chosen)):
            if j in legs_by_stop:
                t += timedelta(minutes=legs_by_stop[j].minutes)
            ops = len(stop.step_indexes) * settings.minutes_per_operation
            states.append(open_during(branch.schedule if branch else None, t, ops, settings.timezone))
            t += timedelta(minutes=ops)
        if any(s is False for s in states):
            route.executable_now = False
            flags.add("HOUSE_CLOSED")
        elif all(s is True for s in states):
            route.executable_now = True
        else:
            route.executable_now = None
            flags.add("HOURS_UNKNOWN")

        route.net_profit_clp -= route.transport_clp
        alt = settings.transport_alt_cost_per_trip_clp
        if alt is not None and route.trips:
            alt_cost = route.trips * alt
            route.alt_transport = {
                "label": settings.transport_alt_label, "cost_per_trip": alt, "transport_clp": alt_cost,
                "net_profit_clp": route.net_profit_clp + route.transport_clp - alt_cost,
            }
        route.profit_percent = route.net_profit_clp / route.initial_clp * 100
        route.flags = sorted(flags)

        conf = confidence_service.assess(route, settings)
        route.confidence, route.confidence_score = conf.level, conf.score
        route.warnings = conf.reasons
    return routes
