"""Configuración central. Todo valor importante viene de variables de entorno / `.env`."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
LOGS_DIR = PROJECT_ROOT / "logs"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", env_file_encoding="utf-8", extra="ignore", env_ignore_empty=True)

    # --- Motor de arbitraje (se usan desde la Fase 2) ---
    initial_capital_clp: float = Field(1_000_000, gt=0)
    base_currency: str = "CLP"
    max_steps: int = Field(5, ge=1)
    top_routes: int = Field(3, ge=1)
    min_net_profit_clp: float = 10_000
    max_quote_age_minutes: int = Field(10, ge=1)
    safety_margin_percent: float = Field(0.5, ge=0)
    # Estados que se conservan por (divisa, paso) durante la búsqueda. Más alto =
    # búsqueda más exhaustiva y más lenta. Ver docs/ENGINE.md.
    search_beam_width: int = Field(100, ge=1)

    # --- Calidad de datos ---
    # Desviación máxima (%) del precio medio de una divisa respecto de la mediana
    # del resto de las casas antes de marcar la cotización como ANOMALOUS_QUOTE.
    anomaly_threshold_percent: float = Field(15.0, gt=0)
    # Mínimo de casas con la misma divisa para poder comparar.
    anomaly_min_peers: int = Field(3, ge=2)

    # --- Comisiones / transporte (Fases 3 y 4) ---
    default_commission_percent: float | None = None
    default_commission_fixed_clp: float | None = None
    transport_mode: str = "public_transport"
    transport_cost_per_km: float = 0.0

    # --- Telegram (Fase 5) ---
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # --- Infraestructura ---
    database_url: str = f"sqlite:///{(DATA_DIR / 'arbitraje.db').as_posix()}"
    log_level: str = "INFO"
    log_file: str = str(LOGS_DIR / "bot.log")

    # --- Scrapers ---
    # Lista separada por comas de slugs de scrapers activos. Vacío = todos los registrados.
    enabled_scrapers: str = "manual_csv"
    scraper_timeout_seconds: float = Field(15, gt=0)
    scraper_retries: int = Field(2, ge=0)
    scraper_backoff_seconds: float = Field(2, ge=0)
    scraper_user_agent: str = "BotCasaCambio/0.1 (+deteccion de arbitraje; contacto en README)"
    respect_robots_txt: bool = True
    houses_file: str = str(DATA_DIR / "exchange_houses.json")
    manual_quotes_file: str = str(DATA_DIR / "manual_quotes.csv")

    @property
    def enabled_scraper_list(self) -> list[str]:
        return [s.strip() for s in self.enabled_scrapers.split(",") if s.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
