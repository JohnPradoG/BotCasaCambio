"""Revisión de todas las webs de casas de cambio (``python -m app.main probe-all``).

Para cada scraper registrado lo ejecuta y anota el resultado. Para cada casa con sitio
web y sin scraper, busca precios en el HTML (tablas o texto "Compra ... Venta ...") y,
si Playwright está instalado, también en la página cargada con navegador, anotando las
respuestas JSON que parezcan cotizaciones. Respeta robots.txt y no reintenta ante
401/403/429.

El resultado (``data/probe/report.json``) sirve para decidir qué scrapers escribir o
corregir; no guarda cotizaciones en la base de datos.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.config.settings import Settings
from app.scrapers.base import BaseScraper
from app.scrapers.extractors import RawRate, extract_rates
from app.scrapers.registry import available_scrapers
from app.services.house_service import load_houses_file


class _Fetcher(BaseScraper):
    slug = "probe"

    def scrape(self):  # pragma: no cover - no se usa
        return []


_rates = extract_rates


def _sample(rates: list[RawRate], n: int = 4) -> list[str]:
    return [f"{r.currency} compra={r.buy_rate} venta={r.sell_rate}" for r in rates[:n]]


def probe_site(url: str, settings: Settings, use_browser: bool, fetcher: BaseScraper | None = None,
               save_dir: Path | None = None) -> dict:
    fetcher = fetcher or _Fetcher(settings)
    if "://" not in url:
        url = f"https://{url}"
    result: dict = {"url": url}
    try:
        resp = fetcher.http_get(url)
        result["http_status"] = resp.status_code
        static = _rates(resp.text)
        result["static_rates"] = len(static)
        result["static_sample"] = _sample(static)
        if save_dir:
            (save_dir / "static.html").write_text(resp.text, encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 - un sitio caído no detiene la revisión
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result
    if use_browser and not static:
        from app.scrapers.browser import render_page

        try:
            html, captured = render_page(url, settings)
            rendered = _rates(html)
            result["rendered_rates"] = len(rendered)
            result["rendered_sample"] = _sample(rendered)
            result["json_sources"] = sorted({c["url"] for c in captured})
            if save_dir:
                (save_dir / "rendered.html").write_text(html, encoding="utf-8")
                (save_dir / "json_responses.json").write_text(
                    json.dumps(captured, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            result["browser_error"] = f"{type(exc).__name__}: {exc}"
    return result


def probe_all(settings: Settings, out_dir: Path, use_browser: bool) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    report: dict = {"generated_at": datetime.now(timezone.utc).isoformat(), "browser": use_browser,
                    "scrapers": {}, "websites": {}}

    for slug, cls in sorted(available_scrapers().items()):
        if slug == "manual_csv":
            continue
        scraper = cls(settings)
        run = scraper.run()
        report["scrapers"][slug] = {
            "url": cls.source_url, "status": run.status.value, "quotes": len(run.quotes), "error": run.error,
            "sample": [f"{q.currency}{f' ({q.branch})' if q.branch else ''} compra={q.buy_rate} venta={q.sell_rate}"
                       for q in run.quotes[:4]],
            "published": sorted({q.timestamp_source.isoformat() for q in run.quotes if q.timestamp_source}),
        }

    if Path(settings.houses_file).exists():
        for house in load_houses_file(settings.houses_file):
            if house.scraper or not house.website:
                continue
            site_dir = out_dir / house.slug
            site_dir.mkdir(parents=True, exist_ok=True)
            report["websites"][house.slug] = probe_site(house.website, settings, use_browser, save_dir=site_dir)

    (out_dir / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


def summarize(report: dict) -> str:
    lines = ["SCRAPERS"]
    for slug, r in report["scrapers"].items():
        extra = f" · {r['error']}" if r.get("error") else ""
        lines.append(f"  {slug:18s} {r['status']:18s} {r['quotes']:3d} cotizaciones{extra}")
    lines.append("WEBS SIN SCRAPER")
    for slug, r in report["websites"].items():
        if r.get("error"):
            state = f"error: {r['error'][:80]}"
        else:
            state = f"{r.get('static_rates', 0)} divisas en HTML"
            if "rendered_rates" in r:
                state += f", {r['rendered_rates']} con navegador"
            if r.get("json_sources"):
                state += f", {len(r['json_sources'])} fuentes JSON"
            if r.get("browser_error"):
                state += f" (navegador: {r['browser_error'][:60]})"
        lines.append(f"  {slug:18s} {state}")
    return "\n".join(lines)
