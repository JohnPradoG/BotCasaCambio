"""Casa de cambio (empresa) y sus sucursales físicas.

Una casa puede tener varias sucursales con la misma cotización publicada; para
calcular distancias (Fase 4) lo que importa es la sucursal física. Todo campo
desconocido queda en None: nunca se rellena con supuestos (SPEC §6).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Branch:
    name: str
    address: str | None = None
    comuna: str | None = None
    phone: str | None = None
    whatsapp: str | None = None
    opening_hours: str | None = None  # texto tal como lo publica la fuente
    latitude: float | None = None
    longitude: float | None = None
    source_url: str | None = None
    verified: bool = False  # True solo si un humano confirmó el dato
    notes: str | None = None


@dataclass
class ExchangeHouse:
    slug: str
    name: str
    website: str | None = None
    quotes_url: str | None = None
    phone: str | None = None
    whatsapp: str | None = None
    source_url: str | None = None
    scraper: str | None = None  # slug del scraper que obtiene sus cotizaciones
    notes: str | None = None
    branches: list[Branch] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "ExchangeHouse":
        data = dict(data)
        branches = [Branch(**b) for b in data.pop("branches", [])]
        return cls(**data, branches=branches)
