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

Un sitio sin precios se vuelve a revisar cada ``DISCOVERY_RETRY_HOURS``; uno que sí publicó
precios en la última semana se sigue revisando en cada ciclo aunque falle una vez (una caída
pasajera no lo deja un día sin leer). El estado queda en
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
from app.services.house_service import load_all_houses

_PRICE_WORDS = ("precio", "cotiza", "valores", "divisa", "tasa", "moneda")
MAX_SUBPAGES = 3
KEEP_TRYING = timedelta(days=7)  # tras encontrar precios, se reintenta en cada ciclo esta cantidad de tiempo
# Redes sociales y enlaces de contacto: no son webs de precios (y suelen prohibir robots).
_SOCIAL = ("instagram.com", "facebook.com", "fb.com", "wa.me", "whatsapp.com", "linktr.ee", "tiktok.com",
           "twitter.com", "x.com", "linkedin.com", "youtube.com", "google.com", "goo.gl", "business.site")


def is_social(url: str) -> bool:
    host = urlsplit(url if "://" in url else f"https://{url}").netloc.lower().removeprefix("www.")
    return any(host == d or host.endswith("." + d) for d in _SOCIAL)


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
        return [h for h in load_all_houses(self.settings)
                if h.website and not h.scraper and not is_social(h.website)]

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
            last_found = prev.get("last_found")
            had_prices = last_found and now - datetime.fromisoformat(last_found) < KEEP_TRYING
            old_format = prev and "last_found" not in prev  # estado de antes de este cambio: probar una vez
            if not prev.get("found") and not had_prices and not old_format and prev.get("last_try"):
                if now - datetime.fromisoformat(prev["last_try"]) < retry:
                    continue
            website = house.website if "://" in house.website else f"https://{house.website}"
            try:
                rates, url = self.find_rates(website)
                error = None
            except Exception as exc:  # noqa: BLE001 - un sitio caído no detiene a los demás
                rates, url, error = [], website, f"{type(exc).__name__}: {exc}"
                self.log.info("%s: %s", house.slug, error)
            state[house.slug] = {"last_try": now.isoformat(), "found": len(rates), "url": url, "error": error,
                                 "last_found": now.isoformat() if rates else last_found}
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
