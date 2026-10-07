"""Configuración central. Todo valor importante viene de variables de entorno / `.env`."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
LOGS_DIR = PROJECT_ROOT / "logs"

TRANSPORT_MODES = ("walk", "public_transport", "car", "taxi")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env", env_file_encoding="utf-8", extra="ignore", env_ignore_empty=True
    )

    # --- Motor de arbitraje ---
    initial_capital_clp: float = Field(1_000_000, gt=0)
    base_currency: str = "CLP"
    max_steps: int = Field(5, ge=1)
    top_routes: int = Field(3, ge=1)
    min_net_profit_clp: float = 0  # avisa cualquier ganancia neta positiva
    safety_margin_percent: float = Field(0, ge=0)
    # Estados que se conservan por (divisa, paso) durante la búsqueda. Más alto =
    # búsqueda más exhaustiva y más lenta. Ver docs/ENGINE.md.
    search_beam_width: int = Field(100, ge=1)
    # Rutas candidatas que se evalúan con distancia/transporte antes de elegir el Top N.
    candidate_routes: int = Field(50, ge=1)
    timezone: str = "America/Santiago"

    # --- Calidad de datos ---
    # Cotización más antigua que esto: se usa, pero baja la confianza (SPEC §36).
    max_quote_age_minutes: int = Field(10, ge=1)
    # Cotización más antigua que esto: no se usa para detectar oportunidades (sí queda en el historial).
    max_quote_usable_hours: float = Field(24, gt=0)
    # Desviación máxima (%) del precio medio de una divisa respecto de la mediana
    # del resto de las casas antes de marcar la cotización como ANOMALOUS_QUOTE.
    anomaly_threshold_percent: float = Field(15.0, gt=0)
    # Mínimo de casas con la misma divisa para poder comparar.
    anomaly_min_peers: int = Field(3, ge=2)

    # --- Dólar de mercado (USDT/CLP) como referencia, no entra a las rutas ---
    # Fuentes en orden (binance, buda); vacío = desactivado.
    market_reference: str = "binance,buda"
    # Aviso "casa fuera de mercado" si el dólar de una casa se aleja más que esto (%).
    market_gap_percent: float = Field(0.3, ge=0)
    # No repetir el aviso de la misma casa y lado antes de estas horas.
    market_alert_cooldown_hours: float = Field(6, ge=0)
    # Diferencia de USDT entre plataformas (comprar en una, vender en otra); vacío = desactivado.
    usdt_venues: str = "buda,binance,cryptomkt"
    # Comisión por operación (%) en esas plataformas; 0 = el aviso dice "antes de comisiones".
    usdt_fee_percent: float = Field(0, ge=0)
    usdt_alert_cooldown_hours: float = Field(2, ge=0)
    # Plataformas cuya API de precios se consulta aunque su robots.txt diga que no
    # (autorizado por John el 2026-10-07; solo lectura de precios públicos, nunca opera).
    robots_exempt_apis: str = "binance,buda,cryptomkt"
    # Cada lectura de USDT se guarda aquí para el backtesting (/backtest).
    usdt_history_file: str = str(DATA_DIR / "usdt_prices.csv")

    # --- Comisiones estimadas manuales (si la casa no publica la suya) ---
    default_commission_percent: float | None = None
    default_commission_fixed_clp: float | None = None

    # --- Transporte y distancias ---
    transport_mode: str = "public_transport"  # walk | public_transport | car | taxi
    transport_cost_per_km: float = Field(0.0, ge=0)
    transport_fixed_cost_per_trip_clp: float = Field(0.0, ge=0)  # p. ej. pasaje o bajada de bandera
    # True: se cobra también el viaje de ida a la primera casa y el de vuelta desde la última
    # (sales de ORIGIN_LAT/ORIGIN_LON y vuelves ahí), aunque falten coordenadas.
    transport_from_home: bool = True
    # Costo alternativo por viaje (p. ej. taxi) solo para mostrar "si vas en taxi quedaría...".
    # No cambia el ranking ni la ganancia neta. Vacío = no se muestra.
    transport_alt_cost_per_trip_clp: float | None = Field(None, ge=0)
    transport_alt_label: str = "taxi"
    # Velocidad promedio (km/h) por modo. Vacío = valor por defecto del modo.
    transport_speed_kmh: float | None = None
    # Factor ciudad: distancia real ≈ línea recta × factor (cuando no hay OSRM).
    route_distance_factor: float = Field(1.3, ge=1)
    # Servidor OSRM opcional (p. ej. https://router.project-osrm.org). Vacío = línea recta × factor.
    osrm_url: str = ""
    # Punto de partida del usuario (opcional). Si no se indica, la ruta parte en la primera casa.
    origin_lat: float | None = None
    origin_lon: float | None = None
    # Minutos estimados de atención por operación en mesón.
    minutes_per_operation: float = Field(10, ge=0)

    # --- Alertas ---
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    # No repetir la alerta de la misma ruta durante este tiempo, salvo que mejore.
    alert_cooldown_minutes: int = Field(60, ge=0)
    # Mejora mínima (%) de la ganancia neta para volver a alertar la misma ruta.
    alert_min_improvement_percent: float = Field(10, ge=0)
    # Avisar si la ganancia neta de una ruta ya alertada cae este % o más (0 = no avisar).
    # Se vigila mientras la oportunidad está vigente (OPPORTUNITY_TTL_MINUTES).
    alert_drop_percent: float = Field(10, ge=0, lt=100)

    # --- Seguimiento ---
    # Oportunidades DETECTED / PENDING_VERIFICATION más antiguas pasan a EXPIRED.
    opportunity_ttl_minutes: int = Field(60, ge=1)

    # --- Infraestructura ---
    database_url: str = f"sqlite:///{(DATA_DIR / 'arbitraje.db').as_posix()}"
    log_level: str = "INFO"
    log_file: str = str(LOGS_DIR / "bot.log")
    loop_interval_seconds: int = Field(180, ge=30)
    # Intervalo más corto en la franja de apertura (hora local "HH:MM-HH:MM"; vacío = no se usa),
    # cuando las casas cambian sus precios y una puede quedar desfasada de otra.
    fast_loop_window: str | None = "09:00-10:30"
    fast_loop_interval_seconds: int = Field(60, ge=30)
    dashboard_host: str = "127.0.0.1"
    dashboard_port: int = 8000
    # Si se define, el panel exige ?token=... o la cabecera X-Token (recomendado si se expone a Internet).
    dashboard_token: str = ""

    # --- Scrapers ---
    # Lista separada por comas de slugs de scrapers activos. Vacío = todos los registrados.
    enabled_scrapers: str = "manual_csv,web_discovery"
    # Descubrimiento automático: webs de casas sin scraper. Reintento de las que no tenían precios.
    discovery_retry_hours: float = Field(24, ge=0)
    discovery_use_browser: bool = True
    # Búsqueda de casas en el mapa: "auto" = Google Maps si hay clave, si no OpenStreetMap (gratis).
    maps_provider: str = "auto"  # auto | osm | google
    osm_overpass_url: str = "https://overpass-api.de/api/interpreter"
    google_maps_api_key: str | None = None
    maps_queries: str = "casas de cambio;casa de cambio"  # como se escribe en Google Maps; varias con ";"
    # Rectángulo lat_min,lon_min,lat_max,lon_max (Gran Santiago) y tamaño de celda en grados.
    maps_bbox: str = "-33.65,-70.85,-33.30,-70.45"
    maps_cell_degrees: float = Field(0.05, gt=0)
    maps_max_requests: int = Field(300, ge=1)  # tope de consultas por búsqueda (costo de la API)
    maps_discovery_days: float = Field(30, ge=0)  # cada cuántos días buscar casas nuevas en el loop (0 = nunca)
    # Pedido diario de precios (enlaces de WhatsApp por Telegram) a casas sin precio reciente.
    price_request_time: str | None = None  # hora local, p. ej. "09:30"; vacío = no enviar
    price_request_currencies: str = "USD,EUR,BRL,ARS,PEN"
    # Hora local del resumen diario "lo más cerca de un arbitraje"; vacío = no enviar.
    near_miss_report_time: str | None = "19:00"
    # Hora local del aviso diario de casas que dejaron de dar precios; vacío = no enviar.
    health_report_time: str | None = "11:00"
    # Una casa leída de su web "falla" si no se lee hace más de estas horas.
    health_stale_hours: float = Field(2, gt=0)
    scraper_timeout_seconds: float = Field(15, gt=0)
    scraper_retries: int = Field(2, ge=0)
    scraper_backoff_seconds: float = Field(2, ge=0)
    scraper_user_agent: str = "BotCasaCambio/0.1 (+deteccion de arbitraje; contacto en README)"
    respect_robots_txt: bool = True
    houses_file: str = str(DATA_DIR / "exchange_houses.json")
    # Casas encontradas en Google Maps (generado por `discover-maps`; vacío = junto a HOUSES_FILE).
    maps_houses_file: str = ""
    manual_quotes_file: str = str(DATA_DIR / "manual_quotes.csv")

    @property
    def enabled_scraper_list(self) -> list[str]:
        return [s.strip() for s in self.enabled_scrapers.split(",") if s.strip()]

    @property
    def maps_houses_path(self) -> str:
        return self.maps_houses_file or str(Path(self.houses_file).with_name("maps_houses.json"))

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)


@lru_cache
def get_settings() -> Settings:
    return Settings()
