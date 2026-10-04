"""Páginas que cargan los precios con JavaScript: se abren con un navegador (Playwright).

Solo se lee lo que cualquier visitante vería: no se llenan formularios, no se
resuelven CAPTCHAs ni se inicia sesión. Playwright es opcional
(``pip install -r requirements-browser.txt && playwright install chromium``).

Mientras la página carga se guardan las respuestas JSON que parezcan cotizaciones,
para poder pasar después a la fuente de datos directa (preferida, SPEC §7).
"""

from __future__ import annotations

import json
import logging
import re

from app.config.settings import Settings
from app.scrapers.base import StructureChangedError
from app.scrapers.extractors import find_rate_records

logger = logging.getLogger(__name__)

_RATE_HINT = re.compile(r"compra|venta|buy|sell|rate|tasa|divisa|currency|dolar|usd", re.IGNORECASE)

# Espera hasta que alguna tabla tenga una celda con un número (precios ya cargados).
_TABLE_FILLED_JS = """() => Array.from(document.querySelectorAll('table td'))
    .some(td => /\\d/.test(td.textContent || ''))"""


def playwright_available() -> bool:
    try:
        import playwright.sync_api  # noqa: F401
    except ImportError:
        return False
    return True


def render_page(url: str, settings: Settings, wait_ms: int = 8000, wait_for_table: bool = True) -> tuple[str, list[dict]]:
    """Devuelve (HTML renderizado, respuestas JSON candidatas)."""
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeout
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise StructureChangedError(
            "la página carga los precios con JavaScript y Playwright no está instalado "
            "(pip install -r requirements-browser.txt && playwright install chromium)"
        ) from exc

    captured: list[dict] = []

    def on_response(response):
        if "json" not in response.headers.get("content-type", ""):
            return
        try:
            body = response.text()
        except Exception:  # noqa: BLE001
            return
        if _RATE_HINT.search(body):
            captured.append({"url": response.url, "status": response.status, "body": body[:200_000]})

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page(user_agent=settings.scraper_user_agent)
            page.on("response", on_response)
            page.goto(url, timeout=settings.scraper_timeout_seconds * 1000)
            if wait_for_table:
                try:
                    page.wait_for_function(_TABLE_FILLED_JS, timeout=wait_ms)
                except PlaywrightTimeout:
                    logger.info("%s: ninguna tabla con números tras %d ms", url, wait_ms)
            page.wait_for_timeout(1500 if wait_for_table else wait_ms)
            html = page.content()
        finally:
            browser.close()

    for item in captured:
        try:
            if find_rate_records(json.loads(item["body"])):
                logger.info("Posible fuente JSON de cotizaciones: %s", item["url"])
        except json.JSONDecodeError:
            continue
    return html, captured
