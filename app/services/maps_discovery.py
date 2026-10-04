"""Búsqueda de casas de cambio en Google Maps (API oficial Places, "Text Search").

Recorre Santiago en una cuadrícula: en cada celda pide "casa de cambio" restringido a
ese rectángulo. Si una celda devuelve el máximo de resultados (60), se divide en cuatro
para no perder casas en zonas densas como el centro.

De cada lugar se guarda solo lo que publica Google Maps: nombre, dirección, coordenadas,
teléfono, web y el enlace al lugar (``source_url``). Nada se completa con supuestos.

Los lugares se agrupan en casas por web o por nombre ("AFEX - Mall X" y "AFEX - Y" son
sucursales de AFEX). Una casa que ya está en ``exchange_houses.json`` no se duplica: solo
se le completa la web o el teléfono si faltaban. El resultado va a ``maps_houses.json``
(no versionado); ``house_service.load_all_houses`` lo une al registro y desde ahí el
descubrimiento web (``web_discovery``) revisa las webs nuevas en busca de precios.

Requiere ``GOOGLE_MAPS_API_KEY`` con "Places API (New)" habilitada.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import requests

from app.config.settings import Settings
from app.models.currency import _strip_accents
from app.models.exchange_house import Branch, ExchangeHouse

logger = logging.getLogger(__name__)

SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
FIELDS = ",".join([
    "places.id", "places.displayName", "places.formattedAddress", "places.location", "places.websiteUri",
    "places.nationalPhoneNumber", "places.internationalPhoneNumber", "places.googleMapsUri",
    "places.businessStatus", "places.primaryType", "nextPageToken",
])
MAX_RESULTS_PER_QUERY = 60  # 3 páginas de 20: límite de la API
MAX_SPLIT_DEPTH = 3

_EXCHANGE_WORDS = re.compile(r"cambio|exchange|divisa|money|forex|currenc|moneda", re.IGNORECASE)
_NOT_EXCHANGE = re.compile(r"\b(banco|bank|caja vecina|servipag|western union|aceite|neumatic|cambio de aceite)\b",
                           re.IGNORECASE)
_BRANCH_SEPARATOR = re.compile(r"\s+[-|–—·(]\s*|\s*,\s*")


@dataclass
class Place:
    id: str
    name: str
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    website: str | None = None
    phone: str | None = None
    maps_url: str | None = None
    status: str | None = None

    @classmethod
    def from_api(cls, p: dict) -> "Place":
        loc = p.get("location") or {}
        return cls(
            id=p["id"], name=(p.get("displayName") or {}).get("text", "").strip(),
            address=p.get("formattedAddress"), latitude=loc.get("latitude"), longitude=loc.get("longitude"),
            website=p.get("websiteUri"), phone=p.get("internationalPhoneNumber") or p.get("nationalPhoneNumber"),
            maps_url=p.get("googleMapsUri"), status=p.get("businessStatus"),
        )


@dataclass
class MapsReport:
    requests: int = 0
    places: int = 0
    exchange_places: int = 0
    houses: int = 0
    new_houses: int = 0
    new_with_website: int = 0
    enriched: list[str] = field(default_factory=list)
    truncated: bool = False


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", _strip_accents(text).lower()).strip("_")


def domain(url: str | None) -> str | None:
    if not url:
        return None
    host = urlsplit(url if "://" in url else f"https://{url}").netloc.lower()
    return host.removeprefix("www.") or None


def brand_name(place_name: str) -> str:
    """"AFEX - Mall Plaza Vespucio" → "AFEX"."""
    return _BRANCH_SEPARATOR.split(place_name, maxsplit=1)[0].strip() or place_name


def is_exchange(place: Place, known_names: set[str]) -> bool:
    if place.status == "CLOSED_PERMANENTLY":
        return False
    name = _strip_accents(place.name)
    if _NOT_EXCHANGE.search(name):
        return False
    return bool(_EXCHANGE_WORDS.search(name) or _EXCHANGE_WORDS.search(domain(place.website) or "")
                or _slugify(brand_name(place.name)) in known_names)


def comuna_from_address(address: str | None) -> str | None:
    """"Agustinas 1066, 8320000 Santiago, Región Metropolitana, Chile" → "Santiago"."""
    if not address:
        return None
    parts = [p.strip() for p in address.split(",")]
    for i, part in enumerate(parts):
        if "region metropolitana" in _strip_accents(part).lower() and i > 0:
            return re.sub(r"^\d+\s*", "", parts[i - 1]).strip() or None
    return None


# --------------------------------------------------------------------------- API


class PlacesClient:
    def __init__(self, settings: Settings, session: requests.Session | None = None):
        self.settings = settings
        self.session = session or requests.Session()
        self.requests = 0

    def search(self, query: str, rect: tuple[float, float, float, float]) -> tuple[list[Place], bool]:
        """Lugares dentro de ``rect`` (lat_min, lon_min, lat_max, lon_max). Devuelve (lugares, lleno)."""
        lat_min, lon_min, lat_max, lon_max = rect
        body = {
            "textQuery": query, "languageCode": "es", "regionCode": "CL", "pageSize": 20,
            "locationRestriction": {"rectangle": {"low": {"latitude": lat_min, "longitude": lon_min},
                                                  "high": {"latitude": lat_max, "longitude": lon_max}}},
        }
        headers = {"X-Goog-Api-Key": self.settings.google_maps_api_key or "", "X-Goog-FieldMask": FIELDS}
        places: list[Place] = []
        token = None
        while True:
            if self.requests >= self.settings.maps_max_requests:
                raise BudgetExceeded
            payload = dict(body, pageToken=token) if token else body
            resp = self.session.post(SEARCH_URL, json=payload, headers=headers,
                                     timeout=self.settings.scraper_timeout_seconds)
            self.requests += 1
            if resp.status_code != 200:
                raise RuntimeError(f"Places API respondió {resp.status_code}: {resp.text[:300]}")
            data = resp.json()
            places += [Place.from_api(p) for p in data.get("places", [])]
            token = data.get("nextPageToken")
            if not token:
                break
        return places, len(places) >= MAX_RESULTS_PER_QUERY


class BudgetExceeded(Exception):
    """Se alcanzó MAPS_MAX_REQUESTS en esta búsqueda."""


def grid(bbox: tuple[float, float, float, float], step: float) -> list[tuple[float, float, float, float]]:
    lat_min, lon_min, lat_max, lon_max = bbox
    cells = []
    lat = lat_min
    while lat < lat_max - 1e-9:
        lon = lon_min
        while lon < lon_max - 1e-9:
            cells.append((lat, lon, min(lat + step, lat_max), min(lon + step, lon_max)))
            lon += step
        lat += step
    return cells


def _split(rect):
    lat_min, lon_min, lat_max, lon_max = rect
    lat_mid, lon_mid = (lat_min + lat_max) / 2, (lon_min + lon_max) / 2
    return [(lat_min, lon_min, lat_mid, lon_mid), (lat_min, lon_mid, lat_mid, lon_max),
            (lat_mid, lon_min, lat_max, lon_mid), (lat_mid, lon_mid, lat_max, lon_max)]


def collect_places(client: PlacesClient, settings: Settings, report: MapsReport) -> dict[str, Place]:
    bbox = tuple(float(x) for x in settings.maps_bbox.split(","))
    queries = [q.strip() for q in settings.maps_queries.split(";") if q.strip()]
    found: dict[str, Place] = {}
    pending = [(rect, 0) for rect in grid(bbox, settings.maps_cell_degrees)]
    try:
        for query in queries:
            stack = list(pending)
            while stack:
                rect, depth = stack.pop()
                places, full = client.search(query, rect)
                for p in places:
                    found.setdefault(p.id, p)
                if full and depth < MAX_SPLIT_DEPTH:
                    stack += [(r, depth + 1) for r in _split(rect)]
    except BudgetExceeded:
        report.truncated = True
        logger.warning("Búsqueda en Maps cortada al llegar a MAPS_MAX_REQUESTS=%d", settings.maps_max_requests)
    report.requests = client.requests
    report.places = len(found)
    return found


# --------------------------------------------------------------------------- agrupación


def group_places(places: list[Place], existing: list[ExchangeHouse], report: MapsReport) -> list[ExchangeHouse]:
    """Convierte lugares en casas. Las ya registradas solo reciben web/teléfono faltantes."""
    by_slug = {h.slug: h for h in existing}
    by_name = {_slugify(h.name): h for h in existing}
    by_domain = {domain(h.website): h for h in existing if domain(h.website)}
    known_names = set(by_slug) | set(by_name)
    out: dict[str, ExchangeHouse] = {}
    enrich: dict[str, ExchangeHouse] = {}

    for p in sorted(places, key=lambda x: x.name.lower()):
        if not is_exchange(p, known_names):
            continue
        report.exchange_places += 1
        brand = brand_name(p.name)
        key = _slugify(brand)
        dom = domain(p.website)
        match = by_domain.get(dom) if dom else None
        match = match or by_slug.get(key) or by_name.get(key)
        if match:
            e = enrich.setdefault(match.slug, ExchangeHouse(slug=match.slug, name=match.name))
            if not match.website and p.website and not e.website:
                e.website, e.source_url = p.website, p.maps_url
            if not match.phone and p.phone and not e.phone:
                e.phone = p.phone
            continue
        # Mismo dominio que una casa nueva ya vista → misma casa.
        house = next((h for h in out.values() if dom and domain(h.website) == dom), None) or out.get(key)
        if house is None:
            house = out[key] = ExchangeHouse(
                slug=key, name=brand, website=p.website, phone=p.phone, source_url=p.maps_url,
                notes="Encontrada en Google Maps (lectura automática, pendiente de verificación humana).",
            )
        house.website = house.website or p.website
        house.branches.append(Branch(
            name=p.name if p.name != brand else (p.address or p.name).split(",")[0],
            address=p.address, comuna=comuna_from_address(p.address), phone=p.phone,
            latitude=p.latitude, longitude=p.longitude, source_url=p.maps_url,
            notes=f"google_place_id={p.id}",
        ))

    report.new_houses = len(out)
    report.new_with_website = sum(1 for h in out.values() if h.website)
    report.enriched = sorted(s for s, e in enrich.items() if e.website or e.phone)
    report.houses = len(out) + len(enrich)
    return list(out.values()) + [e for e in enrich.values() if e.website or e.phone]


def discover(settings: Settings, existing: list[ExchangeHouse], client: PlacesClient | None = None) -> MapsReport:
    if not settings.google_maps_api_key:
        raise RuntimeError("Falta GOOGLE_MAPS_API_KEY en .env")
    report = MapsReport()
    places = collect_places(client or PlacesClient(settings), settings, report)
    houses = group_places(list(places.values()), existing, report)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "Google Maps (Places API, Text Search)",
        "queries": settings.maps_queries, "report": asdict(report),
        "exchange_houses": [asdict(h) for h in houses],
    }
    path = Path(settings.maps_houses_path)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Maps: %d lugares, %d casas de cambio, %d casas nuevas (%d con web) → %s",
                report.places, report.exchange_places, report.new_houses, report.new_with_website, path)
    return report


def summary_text(report: MapsReport) -> str:
    text = (f"🗺️ Búsqueda en Google Maps: {report.exchange_places} locales de cambio encontrados.\n"
            f"Casas nuevas: {report.new_houses} ({report.new_with_website} con web; el bot revisará "
            f"si publican precios).")
    if report.enriched:
        text += f"\nSe completó web/teléfono de: {', '.join(report.enriched)}."
    if report.truncated:
        text += "\n(Se cortó por el límite de consultas MAPS_MAX_REQUESTS.)"
    return text
