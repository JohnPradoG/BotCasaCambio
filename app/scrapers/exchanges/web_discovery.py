"""Descubrimiento automático: busca precios en la web de cada casa registrada sin scraper.

Para cada casa de ``data/exchange_houses.json`` con ``website`` y sin ``scraper``:

1. lee la portada y busca una tabla Moneda | Compra | Venta o texto "Compra X · Venta Y";
2. si no hay, prueba hasta 3 enlaces del mismo sitio que hablen de precios
   ("precios", "cotizaciones", "valores", "divisas", "tasas");
3. si sigue sin precios y Playwright está instalado, abre la portada con navegador.

Las cotizaciones encontradas llevan la bandera ``AUTO_DISCOVERED``: las rutas que las usan
quedan como ``PENDING_VERIFICATION`` y con menos confianza, porque nadie revisó cómo publica
esa casa sus columnas. Solo se aceptan columnas con etiqueta clara de compra/venta; una
ambigua se descarta (``classify_rate_label``).

Un sitio sin precios se vuelve a revisar cada ``DISCOVERY_RETRY_HOURS``. El estado queda en
``data/discovery_state.json``. Respeta robots.txt; un sitio caído no detiene a los demás.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from app.models.quote import NormalizedQuote, QuoteFlag
from app.scrapers.base import BaseScraper
from app.scrapers.extractors import RawRate, extract_rates
from app.scrapers.registry import register
from app.services.house_service import load_houses_file

_PRICE_WORDS = ("precio", "cotiza", "valores", "divisa", "tasa", "moneda")
MAX_SUBPAGES = 3


def price_links(html: str, base_url: str, limit: int = MAX_SUBPAGES) -> list[str]:
    """Enlaces del mismo sitio cuyo texto o dirección habla de precios."""
    host = urlsplit(base_url).netloc.removeprefix("www.")
    links: list[str] = []
    for a in BeautifulSoup(html, "html.parser").find_all("a", href=True):
        url = urljoin(base_url, a["href"]).split("#")[0]
        if urlsplit(url).netloc.removeprefix("www.") != host or url.rstrip("/") == base_url.rstrip("/"):
            continue
        text = f"{a.get_text(' ', strip=True)} {url}".lower()
        if any(w in text for w in _PRICE_WORDS) and url not in links:
            links.append(url)
        if len(links) >= limit:
            break
    return links


@register
class WebDiscoveryScraper(BaseScraper):
    slug = "web_discovery"
    source_url = "data/exchange_houses.json"
    verified = False
    empty_is_ok = True  # que ninguna web publique precios no es un error

    @property
    def state_file(self) -> Path:
        return Path(self.settings.houses_file).with_name("discovery_state.json")

    def _load_state(self) -> dict:
        try:
            return json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save_state(self, state: dict) -> None:
        try:
            self.state_file.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
        except OSError as exc:
            self.log.warning("No se pudo guardar %s: %s", self.state_file, exc)

    def candidates(self) -> list:
        if not Path(self.settings.houses_file).exists():
            return []
        return [h for h in load_houses_file(self.settings.houses_file) if h.website and not h.scraper]

    def find_rates(self, url: str) -> tuple[list[RawRate], str]:
        """Devuelve (tasas, url donde se encontraron)."""
        html = self.http_get(url).text
        rates = extract_rates(html)
        if rates:
            return rates, url
        for link in price_links(html, url):
            try:
                rates = extract_rates(self.http_get(link).text)
            except Exception as exc:  # noqa: BLE001
                self.log.info("%s: %s", link, exc)
                continue
            if rates:
                return rates, link
        if self.settings.discovery_use_browser:
            from app.scrapers.browser import playwright_available, render_page

            if playwright_available():
                rendered, _ = render_page(url, self.settings)
                rates = extract_rates(rendered)
                if rates:
                    return rates, url
        return [], url

    def scrape(self) -> list[NormalizedQuote]:
        now = datetime.now(timezone.utc)
        state = self._load_state()
        retry = timedelta(hours=self.settings.discovery_retry_hours)
        quotes: list[NormalizedQuote] = []
        for house in self.candidates():
            prev = state.get(house.slug, {})
            if not prev.get("found") and prev.get("last_try"):
                if now - datetime.fromisoformat(prev["last_try"]) < retry:
                    continue
            try:
                rates, url = self.find_rates(house.website)
                error = None
            except Exception as exc:  # noqa: BLE001 - un sitio caído no detiene a los demás
                rates, url, error = [], house.website, f"{type(exc).__name__}: {exc}"
                self.log.info("%s: %s", house.slug, error)
            state[house.slug] = {"last_try": now.isoformat(), "found": len(rates), "url": url, "error": error}
            for r in rates:
                quotes.append(NormalizedQuote(
                    exchange_house=house.slug, currency=r.currency, buy_rate=r.buy_rate, sell_rate=r.sell_rate,
                    source_url=url, flags={QuoteFlag.AUTO_DISCOVERED},
                    notes="lectura automática de la web (sin scraper revisado); verificar antes de ir",
                ))
            if rates:
                self.log.info("Descubrimiento: %s publica %d divisas en %s", house.slug, len(rates), url)
        self._save_state(state)
        return quotes
