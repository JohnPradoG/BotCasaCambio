"""Registro de scrapers. Cada módulo de ``exchanges/`` se registra con ``@register``."""

from __future__ import annotations

import importlib
import pkgutil

from app.scrapers.base import BaseScraper

_REGISTRY: dict[str, type[BaseScraper]] = {}


def register(cls: type[BaseScraper]) -> type[BaseScraper]:
    if not cls.slug:
        raise ValueError(f"{cls.__name__} no define slug")
    if cls.slug in _REGISTRY and _REGISTRY[cls.slug] is not cls:
        raise ValueError(f"slug duplicado: {cls.slug}")
    _REGISTRY[cls.slug] = cls
    return cls


def _discover() -> None:
    from app.scrapers import exchanges

    for mod in pkgutil.iter_modules(exchanges.__path__):
        importlib.import_module(f"{exchanges.__name__}.{mod.name}")


def available_scrapers() -> dict[str, type[BaseScraper]]:
    _discover()
    return dict(_REGISTRY)


def get_scrapers(slugs: list[str] | None = None, **kwargs) -> list[BaseScraper]:
    """Instancia los scrapers pedidos (todos si ``slugs`` está vacío)."""
    registry = available_scrapers()
    if not slugs:
        slugs = list(registry)
    unknown = [s for s in slugs if s not in registry]
    if unknown:
        raise KeyError(f"scrapers desconocidos: {unknown}. Disponibles: {sorted(registry)}")
    return [registry[s](**kwargs) for s in slugs]
