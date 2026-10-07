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
| `brollano` | Cambios Brollano (Providencia y Agustinas, una página por sucursal) | **sin verificar en vivo**: tabla HTML con fecha publicada por sucursal; una página con fecha vieja no se usa. |
| `cambio_costero` | Cambio Costero (3 locales en el centro) | **sin verificar en vivo**: solo publica su precio de venta (la compra queda vacía). |
| `inmonex` | Inmonex (inmonex.cl, Santiago Centro) | **sin verificar en vivo**: tabla HTML estática, sin hora publicada; la casa negocia la tasa del día en sucursal. |
| `more_exchange` | More Exchange (precios de la Casa Central San Sebastián) | **sin verificar**: tabla cargada con JavaScript; se lee con navegador (Playwright). |
| `cambios_santiago` | Cambios Santiago (cstgo.cl, Providencia) | **sin verificar**: tabla "Compramos/Vendemos" cargada con JavaScript; se lee con navegador. |
| `orion` | Cambios Orion (Agustinas 1035) | **sin verificar**: tabla Divisa/Compra/Venta en /divisas cargada con JavaScript; se lee con navegador. |
| `web_discovery` | todas las casas registradas con web y sin scraper propio | automático: busca una tabla de precios en la portada, en enlaces de "precios"/"cotizaciones" y, si hay Playwright, con navegador. Sus precios quedan con bandera `AUTO_DISCOVERED` (ruta "por verificar" y menos confianza). Activo por defecto. |
| `afex` | AFEX (afex.cl) | **sin verificar**: el sitio carga los precios con JavaScript y no se pudo inspeccionar desde el entorno de desarrollo. Ejecutar `python -m app.main probe afex` en el VPS para confirmarlo o ajustarlo. Desactivado por defecto. |

**Revisar todo de una vez:** `python -m app.main probe-all` ejecuta cada scraper y revisa la web
de cada casa registrada; deja el resultado en `data/probe/report.json`.

Gamaex, Cambios Lyon e Inmonex se leyeron el 2026-10-03 a través de una conversión a
texto de sus páginas (el entorno de desarrollo no puede descargar sitios .cl), así que
falta probarlos contra el HTML real: `python -m app.main scrape --only gamaex` (y lo mismo
con `cambios_lyon` e `inmonex`). Si devuelven cotizaciones, agrégalos a `ENABLED_SCRAPERS`.

More Exchange (moreexchange.cl) y Cambios Santiago (cstgo.cl) publican precios, pero los cargan
con JavaScript y todavía no tienen scraper. Las demás casas registradas (40 en total, la
mayoría en el centro) no publican precios en internet: sus precios se cargan con `/precio`
o `add-quote`.

Los datos de casas en `data/exchange_houses.json` vienen de fuentes públicas, con su
`source_url`. Lo que no se pudo confirmar queda en `null` y con `verified: false`.

## Instalación en Linux (Ubuntu/Debian, VPS económico)

Instalación en un comando (como root; pide el token y el chat id de Telegram, deja el bot
corriendo con systemd y revisa todas las webs). Se puede repetir para actualizar:

```bash
curl -fsSL https://raw.githubusercontent.com/JohnPradoG/BotCasaCambio/main/scripts/install_vps.sh | bash
```

Paso a paso:

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
| Ganancia mínima para alertar | `MIN_NET_PROFIT_CLP` | `0` (cualquier ganancia) |
| Aviso si una ruta avisada baja su ganancia | `ALERT_DROP_PERCENT` (0 = no avisar) | `10` |
| Margen de seguridad (% que se empeora cada tasa) | `SAFETY_MARGIN_PERCENT` | `0` |
| Antigüedad que baja la confianza | `MAX_QUOTE_AGE_MINUTES` | `10` |
| Comisión estimada manual | `DEFAULT_COMMISSION_PERCENT`, `DEFAULT_COMMISSION_FIXED_CLP` | vacía (desconocida) |
| Distancias por calle | `OSRM_URL` | vacío (línea recta × 1,3) |
| Punto de partida | `ORIGIN_LAT`, `ORIGIN_LON` | vacío (parte en la 1.ª casa) |
| Frecuencia del ciclo | `LOOP_INTERVAL_SECONDS` | `180` |
| Frecuencia en la franja de apertura | `FAST_LOOP_WINDOW` / `FAST_LOOP_INTERVAL_SECONDS` | `09:00-10:30` / `60` |
| Scrapers activos | `ENABLED_SCRAPERS` | `manual_csv` |
| Base de datos | `DATABASE_URL` | SQLite en `data/arbitraje.db` |

Ejemplo en metro, saliendo de casa: `TRANSPORT_FIXED_COST_PER_TRIP_CLP=900`. Una ruta con dos
casas cuesta 3 pasajes (casa → A, A → B, B → casa), aunque falten coordenadas
(`TRANSPORT_FROM_HOME=true`). Para ver también cuánto quedaría en taxi, sin cambiar el ranking:
`TRANSPORT_ALT_COST_PER_TRIP_CLP=5000`. Las coordenadas de tu casa se obtienen con
`python scripts/geocode_branches.py --origin "Calle 123, Comuna"` y van en `ORIGIN_LAT`/`ORIGIN_LON`.

Para pasar a PostgreSQL: `pip install "psycopg[binary]"` y
`DATABASE_URL=postgresql+psycopg://usuario:clave@host:5432/arbitraje`.

### Telegram

1. En Telegram, habla con **@BotFather**, envía `/newbot` y copia el token en `TELEGRAM_BOT_TOKEN`.
2. Envía cualquier mensaje a tu bot nuevo.
3. Ejecuta `python -m app.main telegram-chat-id` y copia la línea `TELEGRAM_CHAT_ID=...` en `.env`
   (o abre `https://api.telegram.org/bot<TOKEN>/getUpdates` y copia `message.chat.id`).
4. Ejecuta `python -m app.main telegram-test`.

Sin Telegram configurado, las alertas quedan en `logs/bot.log`.

### Cargar precios desde el celular (casas sin precios en internet)

Muchas casas del centro solo tienen pizarra. Con `loop` corriendo y Telegram configurado,
escríbele al bot desde el chat configurado (los demás chats se ignoran):

```text
/precio gamaex USD 970 990        casa, divisa, compra, venta (- si no sabes uno)
/precio Cambios Lyon euro 1085 -
/top                              mejores rutas con lo guardado
/casas                            nombres de casas registradas
/lista                            planilla de casas con y sin precio, con teléfonos (también: python -m app.main export-houses --telegram)
/precios                          mejores precios de hoy por divisa; /precios USD = todas las casas
/cerca                            por divisa, la ruta más cercana a dar ganancia y cuánto le falta
/estado                           qué casas con precio en la web se están leyendo bien
/prueba                           alerta de ejemplo (casas ficticias, no se guarda) y cuántas rutas reales hay
/actualizar                       git pull --ff-only + reinicio (systemd Restart=always); solo el chat autorizado
```

Cada precio queda en `data/manual_quotes.csv` con su hora (reemplaza el anterior de esa
casa y divisa) y el bot responde con la mejor ruta. Sin Telegram:
`python -m app.main add-quote gamaex USD 970 990 --source tel:+5622...`.
Compra = lo que la casa te paga por 1 unidad; venta = lo que te cobra.

### Qué tan cerca estuvo cada divisa

Aunque no haya arbitraje, el bot guarda cada ciclo, por divisa, el mejor "comprar en la
casa más barata y vender en la que más paga" (con el margen de seguridad, antes del metro)
y a las `NEAR_MISS_REPORT_TIME` (19:00; vacío lo desactiva) manda el mejor momento del día.
`/cerca` muestra lo de ahora. No cambia las alertas: sirve para decidir con datos si bajar
márgenes o sumar casas.

### Casas que dejan de dar precios

`/estado` lista las casas que el bot leyó de su web en la última semana: ✅ leída hace
poco, ❌ no se lee hace más de `HEALTH_STALE_HOURS` (2), ⚠️ la web muestra precios
publicados hace más de `MAX_QUOTE_USABLE_HOURS` (no se usan). A las `HEALTH_REPORT_TIME`
(11:00; vacío lo desactiva) llega un aviso solo si alguna casa tiene problema.

### Diferencia de USDT entre plataformas

Con los precios de Buda.com, Binance P2P, CryptoMarket (ticker público), Bybit P2P y OKX P2P, el bot revisa si
comprar USDT en una y venderlo en otra deja ganancia con el capital
(`USDT_VENUES=buda,binance,cryptomkt,bybit,okx`; vacío lo
desactiva). Comisión por operación en `USDT_FEE_PERCENT` (0 = el aviso dice "antes de
comisiones"); aviso como máximo cada `USDT_ALERT_COOLDOWN_HOURS` (2) por par. Solo avisa.

Estas plataformas piden en su robots.txt no leer sus API. John autorizó el 2026-10-07
leerlas igual (solo precios públicos, unas pocas consultas cada ciclo):
`ROBOTS_EXEMPT_APIS=binance,buda,cryptomkt,bybit,okx`. Las casas de cambio siguen respetando robots.txt.

`/backtest [días]` (o `python -m app.main backtest-usdt --days 7`) cuenta cuántas veces hubo
ganancia: (1) con las lecturas que el bot guarda en `USDT_HISTORY_FILE` (fiel, incluye
Binance) y (2) con la historia pública de Buda (operaciones) y CryptoMarket (velas de 15 min),
que es aproximada porque son precios de operaciones pasadas, no ofertas.

### Dólar de mercado (Binance P2P / Buda)

`/precios` y las alertas muestran el precio del USDT/CLP como referencia del dólar de
mercado: primero Binance P2P (anuncios para el monto del capital) y, si no responde o su
robots.txt no lo permite, el ticker público de Buda.com (`MARKET_REFERENCE=binance,buda`;
vacío lo desactiva). No entra al cálculo de rutas: el USDT no es billete y ninguna casa lo
cambia. Si el dólar de una casa se aleja más de `MARKET_GAP_PERCENT` (0,3 %) del mercado
(vende bajo lo que paga el mercado, o compra sobre lo que cobra), llega un aviso
"CASA FUERA DE MERCADO", como máximo una vez cada `MARKET_ALERT_COOLDOWN_HOURS` (6) por casa.

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

## Buscar casas en el mapa (OpenStreetMap o Google Maps)

El bot busca en el mapa de Santiago las casas de cambio que no tiene registradas y guarda
nombre, dirección, coordenadas, teléfono y web de cada local en `data/maps_houses.json`.
Las casas nuevas con web pasan al descubrimiento automático (`web_discovery`), que busca si
publican precios. Ejecutar a mano: `python -m app.main discover-maps`.

**Por defecto usa OpenStreetMap**, gratis y sin clave: una consulta a la API pública
Overpass por locales etiquetados como casa de cambio (`amenity=bureau_de_change`) o con
"cambio"/"exchange"/"divisa" en el nombre (datos © colaboradores de OpenStreetMap, ODbL).
Tiene menos locales registrados que Google Maps.

**Google Maps (opcional, requiere facturación en Google Cloud).** Con `GOOGLE_MAPS_API_KEY`
puesta (o `MAPS_PROVIDER=google`) busca "casas de cambio" celda por celda (las zonas densas,
como el centro, se dividen en celdas más chicas). Usa la API oficial (Places API), no lee
la página de Google Maps:

1. En https://console.cloud.google.com crea un proyecto y activa la facturación
   (Google da un cupo gratis mensual; una búsqueda mensual usa del orden de 100-300 consultas).
2. En "APIs y servicios" → "Biblioteca" habilita **Places API (New)**.
3. En "Credenciales" crea una **clave de API** y restríngela a Places API.
4. Ponla en `.env` como `GOOGLE_MAPS_API_KEY=...` y ejecuta `python -m app.main discover-maps`.

El loop busca casas nuevas una vez al mes (`MAPS_DISCOVERY_DAYS=30`) y avisa por
Telegram cuántas casas encontró. `MAPS_MAX_REQUESTS` limita las consultas por búsqueda.

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

   Si la casa tiene web y no le haces scraper, `web_discovery` igual intentará leer sus precios.
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
