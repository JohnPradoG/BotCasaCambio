"""Distancias y tiempos entre sucursales (SPEC §17-§18).

Interfaz ``DistanceProvider`` con dos implementaciones:

* ``StraightLineProvider`` (por defecto, gratis y sin red): distancia en línea
  recta (Haversine) × ``ROUTE_DISTANCE_FACTOR`` y velocidad promedio del modo.
* ``OSRMProvider``: usa un servidor OSRM (``OSRM_URL``) y, si falla, cae a la
  línea recta. Para Google Maps u otro proveedor basta implementar ``leg()``.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

import requests

from app.config.settings import Settings

logger = logging.getLogger(__name__)

# km/h promedio en Santiago; ajustables con TRANSPORT_SPEED_KMH.
DEFAULT_SPEED_KMH = {"walk": 4.5, "public_transport": 18.0, "car": 22.0, "taxi": 22.0}
OSRM_PROFILE = {"walk": "foot", "public_transport": "driving", "car": "driving", "taxi": "driving"}


@dataclass(frozen=True)
class Leg:
    km: float
    minutes: float
    source: str  # "straight_line" | "osrm"


class DistanceProvider(Protocol):
    def leg(self, a: tuple[float, float], b: tuple[float, float]) -> Leg: ...


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


class StraightLineProvider:
    def __init__(self, mode: str = "public_transport", factor: float = 1.3, speed_kmh: float | None = None):
        self.mode = mode
        self.factor = factor
        self.speed = speed_kmh or DEFAULT_SPEED_KMH.get(mode, 18.0)

    def leg(self, a, b) -> Leg:
        km = haversine_km(a, b) * self.factor
        return Leg(km=km, minutes=km / self.speed * 60, source="straight_line")


class OSRMProvider:
    def __init__(self, base_url: str, mode: str, fallback: StraightLineProvider, timeout: float = 5):
        self.base_url = base_url.rstrip("/")
        self.profile = OSRM_PROFILE.get(mode, "driving")
        self.fallback = fallback
        self.timeout = timeout
        self._cached = lru_cache(maxsize=4096)(self._fetch)

    def _fetch(self, a, b) -> Leg | None:
        url = f"{self.base_url}/route/v1/{self.profile}/{a[1]},{a[0]};{b[1]},{b[0]}?overview=false"
        try:
            data = requests.get(url, timeout=self.timeout).json()
            route = data["routes"][0]
            return Leg(km=route["distance"] / 1000, minutes=route["duration"] / 60, source="osrm")
        except Exception as exc:  # noqa: BLE001 - cualquier falla cae a línea recta
            logger.warning("OSRM no respondió (%s); se usa línea recta", exc)
            return None

    def leg(self, a, b) -> Leg:
        return self._cached(tuple(a), tuple(b)) or self.fallback.leg(a, b)


def make_provider(settings: Settings) -> DistanceProvider:
    straight = StraightLineProvider(settings.transport_mode, settings.route_distance_factor, settings.transport_speed_kmh)
    if settings.osrm_url:
        return OSRMProvider(settings.osrm_url, settings.transport_mode, straight)
    return straight


def transport_cost(km: float, trips: int, settings: Settings) -> float:
    """Costo estimado en CLP: por km + costo fijo por traslado (pasaje, bajada de bandera)."""
    return km * settings.transport_cost_per_km + trips * settings.transport_fixed_cost_per_trip_clp
