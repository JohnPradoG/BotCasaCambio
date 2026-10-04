"""Casas de cambio de OpenStreetMap (gratis, sin clave) vía la API pública Overpass.

Una sola consulta por búsqueda: locales con ``amenity=bureau_de_change`` (la etiqueta de
casa de cambio en OSM) más comercios u oficinas con "cambio", "exchange" o "divisa" en el
nombre, dentro de ``MAPS_BBOX``. De cada uno se guarda solo lo que publica el mapa; el
enlace al objeto en openstreetmap.org queda como ``source_url``.

Datos © colaboradores de OpenStreetMap, licencia ODbL. Overpass pide consultas
esporádicas e identificadas: el bot la usa una vez al mes con su User-Agent.
"""

from __future__ import annotations

import logging

import requests

from app.config.settings import Settings
from app.services.maps_discovery import Place

logger = logging.getLogger(__name__)

_NAME = '"name"~"cambio|exchange|divisa",i'
OVERPASS_QUERY_DOC = 'amenity=bureau_de_change; name~"cambio|exchange|divisa" con shop/amenity/office'


def build_query(bbox: str, timeout: int) -> str:
    lat_min, lon_min, lat_max, lon_max = (float(x) for x in bbox.split(","))
    b = f"({lat_min},{lon_min},{lat_max},{lon_max})"
    return (f"[out:json][timeout:{timeout}];("
            f'nwr["amenity"="bureau_de_change"]{b};'
            f"nwr[{_NAME}][shop]{b};nwr[{_NAME}][amenity]{b};nwr[{_NAME}][office]{b};"
            ");out center tags;")


def _address(tags: dict) -> str | None:
    street = " ".join(x for x in (tags.get("addr:street"), tags.get("addr:housenumber")) if x)
    parts = [street, tags.get("addr:city") or tags.get("addr:suburb")]
    return ", ".join(p for p in parts if p) or tags.get("addr:full") or None


def place_from_element(el: dict) -> Place | None:
    tags = el.get("tags") or {}
    name = (tags.get("name") or tags.get("brand") or "").strip()
    if not name:
        return None  # sin nombre no se puede identificar la casa; no se inventa uno
    lat = el.get("lat", (el.get("center") or {}).get("lat"))
    lon = el.get("lon", (el.get("center") or {}).get("lon"))
    oid = f"{el['type']}/{el['id']}"
    return Place(
        id=oid, name=name, address=_address(tags), latitude=lat, longitude=lon,
        website=tags.get("website") or tags.get("contact:website") or tags.get("url"),
        phone=tags.get("phone") or tags.get("contact:phone"),
        maps_url=f"https://www.openstreetmap.org/{oid}",
        status="CLOSED_PERMANENTLY" if "disused:amenity" in tags or tags.get("disused") == "yes" else None,
        comuna=tags.get("addr:city") or tags.get("addr:suburb"),
        tagged_exchange=tags.get("amenity") == "bureau_de_change", source="OpenStreetMap",
    )


def fetch_osm_places(settings: Settings, session: requests.Session | None = None) -> list[Place]:
    timeout = int(max(settings.scraper_timeout_seconds, 90))
    resp = (session or requests.Session()).post(
        settings.osm_overpass_url, data={"data": build_query(settings.maps_bbox, timeout)},
        headers={"User-Agent": settings.scraper_user_agent}, timeout=timeout + 30,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"OpenStreetMap (Overpass) respondió {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    elements = data.get("elements", [])
    if not elements and data.get("remark"):
        raise RuntimeError(f"OpenStreetMap (Overpass) no completó la búsqueda: {data['remark'][:300]}")
    places = [p for p in (place_from_element(e) for e in elements) if p]
    logger.info("OpenStreetMap: %d objetos, %d con nombre", len(elements), len(places))
    return places
