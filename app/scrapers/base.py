"""Scraper base: timeout, reintentos, robots.txt, validación y aislamiento de errores (SPEC §7, §43).

Cada casa de cambio tiene su propio módulo en ``app/scrapers/exchanges/`` que
hereda de :class:`BaseScraper` e implementa solo :meth:`scrape`. ``run()`` se
encarga de todo lo demás y **nunca lanza excepciones**: un scraper roto se
registra como fallido y el resto sigue funcionando.
"""

from __future__ import annotations

import logging
import time
import urllib.robotparser
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from functools import lru_cache
from urllib.parse import urlsplit

import requests

from app.config.settings import Settings, get_settings
from app.models.quote import NormalizedQuote, QuoteValidationError, utcnow

logger = logging.getLogger(__name__)


class ScraperStatus(str, Enum):
    OK = "OK"
    PARTIAL = "PARTIAL"  # algunas filas inválidas descartadas
    STRUCTURE_CHANGED = "STRUCTURE_CHANGED"  # la página cargó pero no se encontraron cotizaciones
    BLOCKED_BY_ROBOTS = "BLOCKED_BY_ROBOTS"
    ERROR = "ERROR"


class ScraperError(Exception):
    pass


class StructureChangedError(ScraperError):
    """La página respondió pero ya no tiene la estructura esperada."""


class RobotsDisallowedError(ScraperError):
    pass


@dataclass
class ScrapeResult:
    scraper: str
    status: ScraperStatus
    quotes: list[NormalizedQuote] = field(default_factory=list)
    error: str | None = None
    rejected: list[str] = field(default_factory=list)
    started_at: datetime = field(default_factory=utcnow)
    finished_at: datetime | None = None

    @property
    def ok(self) -> bool:
        return self.status in (ScraperStatus.OK, ScraperStatus.PARTIAL)


@lru_cache(maxsize=64)
def _robots_for(base_url: str, user_agent: str, timeout: float) -> urllib.robotparser.RobotFileParser | None:
    parser = urllib.robotparser.RobotFileParser()
    try:
        resp = requests.get(f"{base_url}/robots.txt", timeout=timeout, headers={"User-Agent": user_agent})
    except requests.RequestException as exc:
        logger.warning("No se pudo leer robots.txt de %s: %s", base_url, exc)
        return None
    if resp.status_code in (401, 403):
        parser.disallow_all = True
    elif resp.status_code >= 400:
        parser.allow_all = True
    else:
        parser.parse(resp.text.splitlines())
    return parser


class BaseScraper(ABC):
    #: identificador único del scraper (se usa en ENABLED_SCRAPERS)
    slug: str = ""
    #: URL principal de donde salen las cotizaciones
    source_url: str = ""
    #: True cuando la estructura del sitio fue verificada contra la página real
    verified: bool = False
    #: True si una respuesta sin cotizaciones es normal (p. ej. archivo manual vacío)
    empty_is_ok: bool = False

    def __init__(self, settings: Settings | None = None, session: requests.Session | None = None):
        self.settings = settings or get_settings()
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", self.settings.scraper_user_agent)
        self.log = logging.getLogger(f"scraper.{self.slug}")

    # ------------------------------------------------------------------ API
    @abstractmethod
    def scrape(self) -> list[NormalizedQuote]:
        """Devuelve las cotizaciones normalizadas. Puede lanzar excepciones."""

    def run(self) -> ScrapeResult:
        result = ScrapeResult(scraper=self.slug, status=ScraperStatus.OK)
        self.log.info("Scraping %s", self.slug)
        try:
            raw_quotes = self.scrape()
        except RobotsDisallowedError as exc:
            result.status, result.error = ScraperStatus.BLOCKED_BY_ROBOTS, str(exc)
        except StructureChangedError as exc:
            result.status, result.error = ScraperStatus.STRUCTURE_CHANGED, str(exc)
        except Exception as exc:  # noqa: BLE001 - un scraper roto no debe tumbar al resto
            result.status, result.error = ScraperStatus.ERROR, f"{type(exc).__name__}: {exc}"
        else:
            for quote in raw_quotes:
                try:
                    result.quotes.append(quote.validate())
                except QuoteValidationError as exc:
                    result.rejected.append(str(exc))
            if result.rejected:
                self.log.warning("%d cotizaciones descartadas: %s", len(result.rejected), result.rejected)
                result.status = ScraperStatus.PARTIAL if result.quotes else ScraperStatus.STRUCTURE_CHANGED
            if not result.quotes and result.status is ScraperStatus.OK and not self.empty_is_ok:
                result.status = ScraperStatus.STRUCTURE_CHANGED
                result.error = "no se encontraron cotizaciones"
        result.finished_at = utcnow()

        if result.ok:
            for q in result.quotes:
                self.log.info("%s %s buy=%s sell=%s", q.exchange_house, q.currency, q.buy_rate, q.sell_rate)
        else:
            self.log.error("Scraper %s falló [%s]: %s", self.slug, result.status.value, result.error)
        return result

    # -------------------------------------------------------------- helpers
    def check_robots(self, url: str) -> None:
        if not self.settings.respect_robots_txt:
            return
        parts = urlsplit(url)
        base = f"{parts.scheme}://{parts.netloc}"
        parser = _robots_for(base, self.settings.scraper_user_agent, self.settings.scraper_timeout_seconds)
        if parser is not None and not parser.can_fetch(self.settings.scraper_user_agent, url):
            raise RobotsDisallowedError(f"robots.txt no permite {url}")

    def http_get(self, url: str, **kwargs) -> requests.Response:
        """GET con robots.txt, timeout y reintentos con backoff exponencial."""
        self.check_robots(url)
        attempts = self.settings.scraper_retries + 1
        last_exc: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                resp = self.session.get(url, timeout=self.settings.scraper_timeout_seconds, **kwargs)
                if resp.status_code in (401, 403, 429):
                    # Bloqueo o límite de tasa: no insistimos (SPEC §7, sin evasión).
                    raise ScraperError(f"HTTP {resp.status_code} en {url}; no se reintenta")
                resp.raise_for_status()
                return resp
            except ScraperError:
                raise
            except requests.RequestException as exc:
                last_exc = exc
                self.log.warning("Intento %d/%d falló para %s: %s", attempt, attempts, url, exc)
                if attempt < attempts:
                    time.sleep(self.settings.scraper_backoff_seconds * 2 ** (attempt - 1))
        raise ScraperError(f"GET {url} falló tras {attempts} intentos: {last_exc}")
