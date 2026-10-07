# CLAUDE.md

Bot de detección de arbitraje entre casas de cambio físicas de Santiago de Chile.
La especificación completa (53 secciones) está en [`docs/SPEC.md`](docs/SPEC.md). Léela antes de cambiar el motor, los scrapers o el modelo de datos.

## Regla central (no negociable)

- Maximizar el **CLP final neto** partiendo de un capital configurable (por defecto 1.000.000 CLP).
- CLP es un nodo normal del grafo: puede ser intermedio (`CLP → USD → CLP → EUR → CLP` es válido).
- El ranking (Top N, por defecto 3) es **solo por ganancia neta en CLP**. Distancia, tiempo, antigüedad de cotización y disponibilidad afectan la *confianza/riesgo*, nunca ocultan una ruta más rentable.
- `MAX_STEPS` configurable (por defecto 5) y prevención de ciclos.
- Normalización: `buy_rate` = precio al que la casa **compra** la divisa al cliente; `sell_rate` = precio al que la casa la **vende**. CLP→X usa `sell_rate`; X→CLP usa `buy_rate`.

## Datos

- **Nunca inventar datos de casas de cambio.** Si un dato no se conoce, `NULL`/`None`.
- Toda casa/cotización guarda su `source_url`.
- Respetar robots.txt y términos de uso; no saltarse CAPTCHAs ni autenticación.
  Única excepción, autorizada por John el 2026-10-07: las API de precios de Binance P2P, Buda,
  CryptoMarket, Bybit P2P y OKX P2P (`ROBOTS_EXEMPT_APIS`). No agregar otras sin que él lo pida.
- El bot solo detecta, calcula, alerta y registra. **Nunca ejecuta operaciones.**

## Desarrollo

- Se construye por fases (SPEC §48). Prioridad: datos correctos > conversión > rutas > cálculo > ganancia neta > distancia > verificación > historial > alertas > UI.
- Python 3.11+, SQLAlchemy (SQLite ahora, PostgreSQL después vía `DATABASE_URL`), configuración por `.env`.
- Tests: `pytest`.
- Un scraper roto nunca debe detener a los demás.
