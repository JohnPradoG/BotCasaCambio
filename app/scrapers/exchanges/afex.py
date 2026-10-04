"""AFEX (https://www.afex.cl): primer scraper real.

Estado: **NO VERIFICADO contra la página en vivo.** Al 2026-10-03 la portada
de afex.cl muestra "Dólar hoy en AFEX — Compra — · Venta —" con los valores
cargados por JavaScript ("actualizando…"), y el entorno donde se escribió este
módulo no pudo acceder al sitio ni a su robots.txt para ver qué endpoint usa.

Por eso el scraper prueba, en orden de preferencia (SPEC §7):

1. JSON embebido (``<script id="__NEXT_DATA__">``, el sitio es Next.js).
2. Tablas HTML con columnas Compra/Venta.
3. Página renderizada con Playwright (si está instalado) y extracción del
   texto "Compra X · Venta Y". Durante el render también se registran las
   respuestas JSON que parezcan cotizaciones, para poder migrar a la API.

Si nada funciona, el resultado es ``STRUCTURE_CHANGED`` y no se guarda ningún
precio. Para completar la verificación, ejecutar en el VPS::

    python -m app.main probe afex

y revisar ``data/probe/afex/``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from bs4 import BeautifulSoup

from app.models.quote import NormalizedQuote
from app.scrapers.base import BaseScraper, StructureChangedError
from app.scrapers.extractors import RawRate, find_inline_rates, find_rate_records, parse_html_rate_table
from app.scrapers.registry import register

HOUSE_SLUG = "afex"
AFEX_URL = "https://www.afex.cl/"


def extract_rates_from_html(html: str) -> tuple[list[RawRate], str]:
    """Extrae cotizaciones de un HTML de AFEX (estático o renderizado). Devuelve (tasas, método)."""
    soup = BeautifulSoup(html, "html.parser")
    next_data = soup.find("script", id="__NEXT_DATA__")
    if next_data and next_data.string:
        try:
            rates = find_rate_records(json.loads(next_data.string))
        except json.JSONDecodeError:
            rates = []
        if rates:
            return rates, "next_data_json"
    rates = parse_html_rate_table(html)
    if rates:
        return rates, "html_table"
    text = soup.get_text(" ", strip=True)
    rates = find_inline_rates(text)
    if rates:
        return rates, "inline_text"
    return [], "none"


def _dedupe(rates: list[RawRate]) -> list[RawRate]:
    seen: dict[str, RawRate] = {}
    for r in rates:
        seen.setdefault(r.currency, r)
    return list(seen.values())


@register
class AfexScraper(BaseScraper):
    slug = "afex"
    source_url = AFEX_URL
    verified = False

    def __init__(self, *args, use_browser: bool = True, **kwargs):
        super().__init__(*args, **kwargs)
        self.use_browser = use_browser

    def scrape(self) -> list[NormalizedQuote]:
        resp = self.http_get(self.source_url)
        rates, method = extract_rates_from_html(resp.text)
        if not rates and self.use_browser:
            html, _ = self.render_with_browser()
            rates, method = extract_rates_from_html(html)
        if not rates:
            raise StructureChangedError(
                "no se encontraron cotizaciones en afex.cl (ver `python -m app.main probe afex`)"
            )
        self.log.info("AFEX: %d divisas extraídas vía %s", len(rates), method)
        return [
            NormalizedQuote(
                exchange_house=HOUSE_SLUG,
                currency=r.currency,
                buy_rate=r.buy_rate,
                sell_rate=r.sell_rate,
                source_url=self.source_url,
                notes=f"extraído vía {method}",
            )
            for r in _dedupe(rates)
        ]

    def render_with_browser(self, wait_ms: int = 8000) -> tuple[str, list[dict]]:
        """Renderiza la página con Playwright y captura respuestas JSON candidatas.

        Solo lee lo que cualquier navegador vería: no interactúa con formularios,
        CAPTCHAs ni sesiones.
        """
        self.check_robots(self.source_url)
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise StructureChangedError(
                "la página requiere JavaScript y Playwright no está instalado "
                "(pip install -r requirements-browser.txt && playwright install chromium)"
            ) from exc

        captured: list[dict] = []

        def on_response(response):
            ctype = response.headers.get("content-type", "")
            if "json" not in ctype:
                return
            try:
                body = response.text()
            except Exception:  # noqa: BLE001
                return
            if re.search(r"compra|venta|buy|sell|rate|tasa|divisa|currency", body, re.IGNORECASE):
                captured.append({"url": response.url, "status": response.status, "body": body[:200_000]})

        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                page = browser.new_page(user_agent=self.settings.scraper_user_agent)
                page.on("response", on_response)
                page.goto(self.source_url, timeout=self.settings.scraper_timeout_seconds * 1000)
                page.wait_for_timeout(wait_ms)
                html = page.content()
            finally:
                browser.close()

        for item in captured:
            try:
                for r in find_rate_records(json.loads(item["body"])):
                    self.log.info("Posible API de cotizaciones: %s (%s)", item["url"], r.currency)
                    break
            except json.JSONDecodeError:
                continue
        return html, captured

    def probe(self, out_dir: Path) -> dict:
        """Guarda HTML estático, HTML renderizado y respuestas JSON para ajustar el scraper."""
        out_dir.mkdir(parents=True, exist_ok=True)
        report: dict = {"url": self.source_url}
        resp = self.http_get(self.source_url)
        (out_dir / "static.html").write_text(resp.text, encoding="utf-8")
        report["static"] = extract_rates_from_html(resp.text)[1]
        html, captured = self.render_with_browser()
        (out_dir / "rendered.html").write_text(html, encoding="utf-8")
        (out_dir / "json_responses.json").write_text(json.dumps(captured, indent=2, ensure_ascii=False), encoding="utf-8")
        rates, method = extract_rates_from_html(html)
        report["rendered"] = method
        report["rates"] = [r.__dict__ | {"raw": str(r.raw)[:300]} for r in rates]
        report["json_responses"] = [c["url"] for c in captured]
        return report
