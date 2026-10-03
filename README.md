# BotCasaCambio: arbitraje entre casas de cambio de Santiago

Detecta rutas de cambio entre casas de cambio físicas de Santiago de Chile que
maximicen el **CLP final neto** partiendo de un capital configurable. El bot solo
**detecta, calcula, alerta y registra**. Nunca compra, vende, transfiere ni reserva.

- Especificación completa: [`docs/SPEC.md`](docs/SPEC.md)
- Arquitectura y decisiones: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- Motor de rutas: [`docs/ENGINE.md`](docs/ENGINE.md)

## Estado

| Fase | Contenido | Estado |
|------|-----------|--------|
| 1 | Arquitectura, configuración, BD, modelos, cotizaciones, scraper base, primer scraper, normalización | ✅ |
| 2 | Grafo, conversiones, rutas 1-5 pasos, CLP intermedio, ciclos, ganancia | ✅ |
| 3 | Múltiples casas/monedas, Top N, comisiones, disponibilidad, montos, cotizaciones antiguas, horarios | ✅ |
| 4 | Distancias, tiempos, transporte, confianza, riesgo | ✅ |
| 5 | Telegram, contactos, mensajes de verificación (teléfono/WhatsApp) | ✅ |
| 6 | Historial, verificación, ejecutadas/fallidas, estadísticas | ✅ |
| 7 | Dashboard FastAPI con mapa | ✅ |
| 8 | Machine Learning | pendiente: requiere historial real acumulado |

### Fuentes de datos

| Scraper | Casa | Estado |
|---------|------|--------|
| `manual_csv` | cualquiera (precios ingresados a mano en `data/manual_quotes.csv`) | funcional |
| `gamaex` | Gamaex (gamaex.cl, Providencia) | **sin verificar en vivo**: tabla HTML estática; columnas "Vendes"/"Compras" (punto de vista del cliente, ya traducidas). La página dice "0% comisiones". |
| `cambios_lyon` | Cambios Lyon (cambioslyon.cl, 3 sucursales) | **sin verificar en vivo**: tabla HTML estática con hora de actualización publicada. Varias divisas solo tienen precio de compra. |
| `inmonex` | Inmonex (inmonex.cl, Santiago Centro) | **sin verificar en vivo**: tabla HTML estática, sin hora publicada; la casa negocia la tasa del día en sucursal. |
| `afex` | AFEX (afex.cl) | **sin verificar**: el sitio carga los precios con JavaScript y no se pudo inspeccionar desde el entorno de desarrollo. Ejecutar `python -m app.main probe afex` en el VPS para confirmarlo o ajustarlo. Desactivado por defecto. |

Gamaex, Cambios Lyon e Inmonex se leyeron el 2026-10-03 a través de una conversión a
texto de sus páginas (el entorno de desarrollo no puede descargar sitios .cl), así que
falta probarlos contra el HTML real: `python -m app.main scrape --only gamaex` (y lo mismo
con `cambios_lyon` e `inmonex`). Si devuelven cotizaciones, agrégalos a `ENABLED_SCRAPERS`.

More Exchange (moreexchange.cl) está registrada con sus sucursales, pero carga los precios
con JavaScript y todavía no tiene scraper; sus precios pueden ir en `data/manual_quotes.csv`.

Los datos de casas en `data/exchange_houses.json` vienen de fuentes públicas, con su
`source_url`. Lo que no se pudo confirmar queda en `null` y con `verified: false`.

## Instalación en Linux (Ubuntu/Debian, VPS económico)

```bash
sudo apt update && sudo apt install -y python3 python3-venv git
sudo useradd -m -s /bin/bash bot          # opcional: usuario dedicado
sudo mkdir -p /opt/BotCasaCambio && sudo chown bot: /opt/BotCasaCambio
sudo -iu bot
git clone https://github.com/JohnPradoG/BotCasaCambio.git /opt/BotCasaCambio
cd /opt/BotCasaCambio
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                        # editar valores
python -m app.main init-db

# Solo para scrapers de sitios con JavaScript (AFEX):
pip install -r requirements-browser.txt
python -m playwright install --with-deps chromium

# Opcional: coordenadas de sucursales para distancias (OpenStreetMap)
python scripts/geocode_branches.py          # revisa
python scripts/geocode_branches.py --write  # guarda
```

### Dejarlo corriendo

Con systemd (recomendado):

```bash
sudo cp deploy/botcasacambio.service deploy/botcasacambio-dashboard.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now botcasacambio botcasacambio-dashboard
journalctl -u botcasacambio -f              # ver logs
```

Con Docker: `cp .env.example .env && docker compose up -d --build`.

El panel escucha en `127.0.0.1:8000`. Para verlo desde tu computador usa un túnel:
`ssh -L 8000:localhost:8000 usuario@vps` y abre http://localhost:8000. Si lo expones a
Internet, define `DASHBOARD_TOKEN` y entra con `http://host:8000/?token=...`.

## Uso

```bash
python -m app.main scrape                 # obtiene cotizaciones
python -m app.main quotes                 # últimas cotizaciones
python -m app.main houses                 # casas registradas / con cotización / sin datos
python -m app.main analyze                # Top N con lo guardado (no alerta)
python -m app.main analyze --capital 5000000 --steps 4 --top 5
python -m app.main run-once               # un ciclo completo: scrape, rutas, guardado y alerta
python -m app.main loop                   # ciclo cada LOOP_INTERVAL_SECONDS
python -m app.main opportunities          # historial de oportunidades
python -m app.main show 125               # detalle + mensajes para verificar por WhatsApp
python -m app.main verify 125             # menú: Verified / Failed / Executed / Expired...
python -m app.main verify 125 --status FAILED --reason "Casa no tenía suficiente USD"
python -m app.main stats                  # estadísticas del historial
python -m app.main telegram-test          # prueba de Telegram
python -m app.main dashboard              # panel web
pytest                                    # tests
```

Cada ciclo (SPEC §52) consulta las casas, guarda **todas** las cotizaciones, calcula las
rutas, elimina las inválidas, calcula ganancia, distancia, tiempo y confianza, guarda el
Top N como oportunidades y envía Telegram solo si una ruta es nueva o mejoró
(`ALERT_MIN_IMPROVEMENT_PERCENT`) y supera `MIN_NET_PROFIT_CLP`. Si después la ganancia de
una ruta ya avisada baja `ALERT_DROP_PERCENT` % o más (por defecto 10%), o la ruta deja de
existir, llega un aviso "⚠️ BAJÓ LA GANANCIA" para no desplazarse de balde. Las oportunidades no
revisadas pasan a `EXPIRED` después de `OPPORTUNITY_TTL_MINUTES`.

## Configuración (`.env`)

Toda la configuración vive en `.env` (ver `.env.example`, comentado). Un valor vacío usa el valor por defecto.

| Qué cambiar | Variable | Por defecto |
|-------------|----------|-------------|
| **Capital inicial** | `INITIAL_CAPITAL_CLP` (o `analyze --capital`) | `1000000` |
| **Número de oportunidades mostradas** | `TOP_ROUTES` (o `--top`) | `3` |
| **Número máximo de pasos** | `MAX_STEPS` (o `--steps`) | `5` |
| **Costo de transporte** | `TRANSPORT_MODE`, `TRANSPORT_COST_PER_KM`, `TRANSPORT_FIXED_COST_PER_TRIP_CLP` | `public_transport`, `0`, `0` |
| Ganancia mínima para alertar | `MIN_NET_PROFIT_CLP` | `10000` |
| Aviso si una ruta avisada baja su ganancia | `ALERT_DROP_PERCENT` (0 = no avisar) | `10` |
| Margen de seguridad (% que se empeora cada tasa) | `SAFETY_MARGIN_PERCENT` | `0.5` |
| Antigüedad que baja la confianza | `MAX_QUOTE_AGE_MINUTES` | `10` |
| Comisión estimada manual | `DEFAULT_COMMISSION_PERCENT`, `DEFAULT_COMMISSION_FIXED_CLP` | vacía (desconocida) |
| Distancias por calle | `OSRM_URL` | vacío (línea recta × 1,3) |
| Punto de partida | `ORIGIN_LAT`, `ORIGIN_LON` | vacío (parte en la 1.ª casa) |
| Frecuencia del ciclo | `LOOP_INTERVAL_SECONDS` | `180` |
| Scrapers activos | `ENABLED_SCRAPERS` | `manual_csv` |
| Base de datos | `DATABASE_URL` | SQLite en `data/arbitraje.db` |

Ejemplo de transporte en taxi: `TRANSPORT_MODE=taxi`, `TRANSPORT_COST_PER_KM=1300`,
`TRANSPORT_FIXED_COST_PER_TRIP_CLP=500`. Estos valores son ejemplos: pon los tuyos.

Para pasar a PostgreSQL: `pip install "psycopg[binary]"` y
`DATABASE_URL=postgresql+psycopg://usuario:clave@host:5432/arbitraje`.

### Telegram

1. En Telegram, habla con **@BotFather**, envía `/newbot` y copia el token en `TELEGRAM_BOT_TOKEN`.
2. Envía cualquier mensaje a tu bot nuevo.
3. Ejecuta `python -m app.main telegram-chat-id` y copia la línea `TELEGRAM_CHAT_ID=...` en `.env`
   (o abre `https://api.telegram.org/bot<TOKEN>/getUpdates` y copia `message.chat.id`).
4. Ejecuta `python -m app.main telegram-test`.

Sin Telegram configurado, las alertas quedan en `logs/bot.log`.

## Cómo se decide el ranking

- Ranking **solo por ganancia neta** = CLP final − capital − comisiones − margen de seguridad − transporte.
- CLP es un nodo más: `CLP → USD → CLP → EUR → CLP` es válido si deja más CLP.
- Distancia, tiempo, antigüedad, horario y disponibilidad no ocultan rutas: se reflejan en
  la **confianza** (0-100, ALTA/MEDIA/BAJA), que nunca cambia el orden.
- Cotizaciones sospechosas (`ANOMALOUS_QUOTE`, `INVERTED_SPREAD`) se mantienen, pero la ruta
  queda en `PENDING_VERIFICATION` con confianza BAJA.
- Casa cerrada: la ruta se guarda como oportunidad futura (`executable_now = false`).

Convención compra/venta: `buy_rate` = la casa **compra** la divisa (se usa para X → CLP);
`sell_rate` = la casa **vende** la divisa (se usa para CLP → X).

## Cómo agregar una casa de cambio

1. **Registrar la casa** en `data/exchange_houses.json` (solo datos públicos, con
   `source_url`; lo desconocido en `null`). Cada sucursal física va en `branches`, con
   coordenadas si las tienes (o `scripts/geocode_branches.py`) y, si el horario está
   publicado completo, `schedule`:
   ```json
   "schedule": {"mon": ["09:00", "18:00"], "tue": ["09:00", "18:00"], "sat": ["10:00", "14:00"], "sun": null}
   ```
   Un día ausente significa desconocido, y `null` significa cerrado.
2. **Cotizaciones**: elige una de estas dos opciones.
   - *Manual*: agrega filas a `data/manual_quotes.csv` con el mismo `exchange_house` (slug).
   - *Scraper*: crea `app/scrapers/exchanges/<slug>.py`:

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

3. Agrega el slug a `ENABLED_SCRAPERS` y prueba con `python -m app.main scrape --only mi_casa`.
4. Agrega un test con un HTML de ejemplo en `tests/fixtures/`.

Si la casa publica una tabla HTML simple, basta con heredar de `HtmlTableScraper`
(`app/scrapers/table_scraper.py`), como `gamaex.py` o `inmonex.py`: solo se declaran el
slug, la URL y, si la página la publica, la hora de actualización.

Si el sitio publica una API o JSON embebido, prefiérelo (`find_rate_records`). Si carga
con JavaScript, usa Playwright como en `afex.py`. Nunca hay que saltarse CAPTCHAs, logins
ni bloqueos: un HTTP 401/403/429 detiene el scraper sin reintentar.

## Principios

- Nunca inventar datos: lo desconocido es `NULL`.
- Un scraper roto no detiene a los demás (queda registrado en `scraper_runs`).
- Se guarda **todo** el historial de cotizaciones, oportunidades y verificaciones.
- Nada está garantizado: confirmar precios y disponibilidad antes de desplazarse.
