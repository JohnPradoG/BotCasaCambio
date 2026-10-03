# BotCasaCambio — Arbitraje entre casas de cambio de Santiago

Detecta rutas de cambio entre casas de cambio físicas de Santiago de Chile que
maximicen el **CLP final neto** partiendo de un capital configurable. El bot solo
**detecta, calcula, alerta y registra**: nunca compra, vende ni transfiere.

- Especificación completa: [`docs/SPEC.md`](docs/SPEC.md)
- Arquitectura y decisiones: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)

## Estado

| Fase | Contenido | Estado |
|------|-----------|--------|
| 1 | Arquitectura, configuración, BD, modelos, cotizaciones, scraper base, primer scraper, normalización | ✅ este PR |
| 2 | Grafo, conversiones, rutas 1-5 pasos, CLP intermedio, ciclos, ganancia | pendiente |
| 3 | Múltiples casas/monedas, Top 3, comisiones, disponibilidad, cotizaciones antiguas | pendiente |
| 4 | Distancias, tiempos, transporte, confianza, riesgo | pendiente |
| 5 | Telegram, contacto, mensajes de verificación | pendiente |
| 6 | Historial, verificación, ejecutadas/fallidas, estadísticas | pendiente |
| 7 | Dashboard FastAPI, mapas | pendiente |
| 8 | Machine Learning | pendiente |

### Fuentes de datos

| Scraper | Casa | Estado |
|---------|------|--------|
| `manual_csv` | cualquiera (precios ingresados a mano en `data/manual_quotes.csv`) | funcional |
| `afex` | AFEX (afex.cl) | **sin verificar**: el sitio carga los precios con JavaScript y no se pudo inspeccionar desde el entorno de desarrollo. Ejecutar `python -m app.main probe afex` en el VPS para confirmar/ajustar. Desactivado por defecto. |

Los datos de casas en `data/exchange_houses.json` vienen de fuentes públicas con su
`source_url`; lo que no se pudo confirmar queda en `null` y `verified: false`.

## Instalación en Linux (Ubuntu/Debian)

```bash
sudo apt update && sudo apt install -y python3 python3-venv git
git clone https://github.com/JohnPradoG/BotCasaCambio.git
cd BotCasaCambio
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # y editar valores

# Solo si se usan scrapers de sitios con JavaScript (AFEX):
pip install -r requirements-browser.txt
python -m playwright install --with-deps chromium
```

Con Docker: `cp .env.example .env && docker compose up -d --build`.

## Ejecución

```bash
python -m app.main init-db            # crea la BD y registra casas de data/exchange_houses.json
python -m app.main scrapers           # lista scrapers, si están activos y verificados
python -m app.main scrape             # ejecuta los scrapers de ENABLED_SCRAPERS
python -m app.main scrape --only afex # ejecuta uno en particular
python -m app.main quotes             # últimas cotizaciones guardadas
python -m app.main houses             # casas descubiertas / con cotización / sin datos
python -m app.main probe afex         # diagnóstico del sitio (guarda en data/probe/afex/)
python -m app.main loop --interval 180  # ciclo continuo cada 3 minutos
pytest                                # tests
```

En un VPS se puede dejar `loop` corriendo con Docker (`restart: unless-stopped`) o con
systemd. Alternativa con cron (cada 3 min):

```cron
*/3 * * * * cd /ruta/BotCasaCambio && .venv/bin/python -m app.main scrape >> logs/cron.log 2>&1
```

## Configuración (`.env`)

Toda la configuración vive en `.env` (ver `.env.example`). Un valor vacío usa el valor por defecto.

| Qué cambiar | Variable | Por defecto |
|-------------|----------|-------------|
| Capital inicial | `INITIAL_CAPITAL_CLP` | `1000000` |
| Número de oportunidades mostradas | `TOP_ROUTES` | `3` |
| Número máximo de pasos | `MAX_STEPS` | `5` |
| Ganancia mínima para alertar | `MIN_NET_PROFIT_CLP` | `10000` |
| Antigüedad máxima de cotización | `MAX_QUOTE_AGE_MINUTES` | `10` |
| Margen de seguridad | `SAFETY_MARGIN_PERCENT` | `0.5` |
| Medio y costo de transporte | `TRANSPORT_MODE`, `TRANSPORT_COST_PER_KM` | `public_transport`, `0` |
| Comisión estimada manual | `DEFAULT_COMMISSION_PERCENT`, `DEFAULT_COMMISSION_FIXED_CLP` | vacía (desconocida) |
| Umbral de cotización anómala | `ANOMALY_THRESHOLD_PERCENT` | `15` |
| Scrapers activos | `ENABLED_SCRAPERS` | `manual_csv` |
| Base de datos | `DATABASE_URL` | SQLite en `data/arbitraje.db` |

> Capital, Top N, pasos, transporte y comisiones los usa el motor de rutas, que llega en
> las Fases 2-4. Las variables ya existen para que la configuración no cambie después.

Para pasar a PostgreSQL: `pip install "psycopg[binary]"` y
`DATABASE_URL=postgresql+psycopg://usuario:clave@host:5432/arbitraje`.

### Telegram (Fase 5)

1. En Telegram, hablar con **@BotFather** → `/newbot` → copiar el token a `TELEGRAM_BOT_TOKEN`.
2. Enviar cualquier mensaje al bot nuevo.
3. Abrir `https://api.telegram.org/bot<TOKEN>/getUpdates` y copiar `message.chat.id` a `TELEGRAM_CHAT_ID`.

## Convención compra/venta (crítico)

`buy_rate` = precio en CLP al que **la casa compra** 1 unidad al cliente (se usa para X → CLP).
`sell_rate` = precio en CLP al que **la casa vende** 1 unidad al cliente (se usa para CLP → X).
Las etiquetas escritas desde el punto de vista del cliente ("Usted compra") se invierten en
`app/scrapers/normalization.py`. Una etiqueta ambigua se descarta.

## Cómo agregar una casa de cambio

1. **Registrar la casa** en `data/exchange_houses.json` (solo datos públicos, con
   `source_url`; lo desconocido en `null`). Cada sucursal física va en `branches`.
2. **Cotizaciones**, una de dos:
   - *Manual*: agregar filas a `data/manual_quotes.csv` con el mismo `exchange_house` (slug).
   - *Scraper*: crear `app/scrapers/exchanges/<slug>.py`:

```python
from app.models.quote import NormalizedQuote
from app.scrapers.base import BaseScraper
from app.scrapers.extractors import parse_html_rate_table
from app.scrapers.registry import register


@register
class MiCasaScraper(BaseScraper):
    slug = "mi_casa"
    source_url = "https://ejemplo.cl/cotizaciones"
    verified = False  # True cuando se haya probado contra la página real

    def scrape(self) -> list[NormalizedQuote]:
        html = self.http_get(self.source_url).text  # robots.txt, timeout y reintentos incluidos
        return [
            NormalizedQuote(exchange_house=self.slug, currency=r.currency,
                            buy_rate=r.buy_rate, sell_rate=r.sell_rate, source_url=self.source_url)
            for r in parse_html_rate_table(html)
        ]
```

3. Agregar el slug a `ENABLED_SCRAPERS` y probar con `python -m app.main scrape --only mi_casa`.
4. Agregar un test con un HTML de ejemplo en `tests/fixtures/`.

Si el sitio publica una API o JSON embebido, preferirlo (`find_rate_records`). Si carga
con JavaScript, usar Playwright como en `afex.py`. Nunca saltarse CAPTCHAs, logins ni
bloqueos: un HTTP 401/403/429 detiene el scraper sin reintentar.

## Principios

- Nunca inventar datos: lo desconocido es `NULL`.
- Un scraper roto no detiene a los demás (queda registrado en `scraper_runs`).
- Se guarda **todo** el historial de cotizaciones.
- El ranking será siempre por ganancia neta en CLP; distancia, tiempo y antigüedad solo
  afectan la confianza.
